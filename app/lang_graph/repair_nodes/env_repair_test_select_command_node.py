"""Node: Select testsuite commands to execute based on test results and environment maturity levels.

Goal:
- Analyze existing test results (pass/fail) to determine current environment maturity level
- Select next test commands that can quickly verify and advance environment to higher maturity levels
- Prioritize representative and feasible test commands within each category

Environment Maturity Levels:
- Installable State: Requires build commands to pass
- Testable State: Requires smoke tests (level3) or unit tests (level4) to be runnable
- Runnable State: Requires main entry (level1) or integration commands (level2) to pass

This node outputs `test_command` as a list of shell commands (strings) to execute next.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger


class TestCommandSelectionOutput(BaseModel):
    """Structured output: Contains selected test command and reasoning."""

    selected_command: str = Field(
        description="A single test command to execute next. This should be a directly executable shell command string. Select the most representative command that can quickly verify or advance the environment maturity level."
    )
    level: str = Field(
        description="The level/category of the selected command. Must be one of: 'build', 'level1', 'level2', 'level3', 'level4'."
    )
    reasoning: str = Field(
        description="Brief explanation of why this command was selected, including current environment maturity assessment."
    )


class EnvRepairTestSelectCommandNode:
    """Select which testsuite commands to run next based on test results and environment maturity strategy."""

    SYS_PROMPT = """\
You are a test selection expert. Your task is to analyze test execution history and select the next test commands to execute that will efficiently verify and advance the environment maturity level.

Environment Maturity Levels (in ascending order):
1. Unknown: Build commands have not passed yet
2. Installable State: Build commands have passed, but no testable/runnable tests have passed
3. Testable State: Build passed, and smoke tests (level3) or unit tests (level4) are runnable
4. Runnable State: Build passed, and main entry (level1) or integration commands (level2) have passed

Test Command Categories:
- build_commands: Build commands (e.g., mvn build, npm build, cargo build) - Required for Installable State
- level1_commands: Main entry commands - Required for Runnable State
- level2_commands: Integration commands - Required for Runnable State
- level3_commands: Smoke tests - Required for Testable State
- level4_commands: Unit tests - Required for Testable State

Selection Strategy:
CRITICAL RULE: You MUST first run build_commands (build level) before running any level1-4 test commands. Only after build commands have PASSED should you proceed to select level1, level2, level3, or level4 commands.

1. Analyze the TEST EXECUTION SUMMARY to understand which commands have been executed, their status, execution count, and current environment maturity level.
2. Check build command status first:
   - If NO build commands have PASSED yet: You MUST select a command from build_commands. Do NOT select any level1-4 commands until at least one build command has passed.
   - If build commands have PASSED: You can proceed to select from level1-4 commands based on the current environment state and maturity level requirements.
3. Core Selection Principle: ALWAYS prioritize selecting the MOST NECESSARY test command based on current environment maturity requirements and necessity. The fundamental principle is to select the command that is most critical for advancing the environment to the next maturity level, regardless of whether it has been executed before.

4. Handling command execution history:
   - If a command has been executed and PASSED: Prioritize selecting other unexecuted commands from the same or higher priority categories. If all critical tests in the current maturity level have passed, consider returning environment verification success.
   - If a command has been executed and FAILED:
     * CRITICAL RULE: If the command is the MOST NECESSARY for advancing environment maturity (based on necessity and priority), you SHOULD continue selecting the SAME command even if it has failed multiple times. The agent will attempt to repair the environment, and you should give it opportunities to fix the issue by re-running the same critical command.
     * Only if a command has failed MANY times (e.g., >= 5 times) AND there are alternative representative tests in the same category/level that could serve the same purpose, you may consider switching to an alternative command. However, if the failed command is the most necessary one, prioritize it over alternatives.
     * The key is: necessity and priority override execution history. A highly necessary command should be selected repeatedly until it passes or until it's clear that an alternative is more appropriate.
5. Selection priority (in order):
   - FIRST PRIORITY: Necessity - Select the command that is MOST NECESSARY for advancing to the next environment maturity level
   - SECOND PRIORITY: If build commands haven't passed, you MUST select from build_commands (build is always most necessary at this stage)
   - THIRD PRIORITY: After build passes, select the single most necessary test for the required level/state (level1-4) based on maturity requirements
   - FOURTH PRIORITY: If multiple commands have similar necessity, prefer commands that haven't been executed yet, or if all have been executed, prefer the one that has failed fewer times
   - Remember: Select ONLY ONE command per execution, and prioritize NECESSITY over execution history
6. Goal: Verify and advance environment maturity by selecting the MOST NECESSARY command. The agent will repair the environment, so you should prioritize necessity and allow the agent multiple attempts to fix critical commands rather than switching prematurely.

Output Requirements:
- selected_command: A SINGLE test command (shell command string) to execute next. You must select the MOST NECESSARY command based on necessity and priority, even if it has been executed and failed before. You must select exactly ONE command.
- level: The level/category of the selected command. Must be one of: 'build', 'level1', 'level2', 'level3', 'level4'. This should match the category of the selected command (e.g., if you select a command from build_commands, level should be 'build').
- reasoning: Brief explanation (2-3 sentences) of the selection, including: (1) why this command is the most necessary for advancing environment maturity, (2) how many times it has been executed (if applicable), and (3) why you chose to continue with this command or switch to an alternative.
"""



    def __init__(self, model: Optional[BaseChatModel] = None, container: Optional[BaseContainer] = None):
        self.model = model
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

        prompt_template = ChatPromptTemplate.from_messages(
            [("system", self.SYS_PROMPT), ("human", "Please analyze the test commands and execution history, then select the next test commands to execute.")]
        )
        structured_llm = model.with_structured_output(TestCommandSelectionOutput)
        self.model_chain = prompt_template | structured_llm


    def __call__(self, state: Dict):
        """Select next test commands based on test results and environment maturity."""
        # Get testsuite commands from state
        testsuite_commands = state.get("test_commands", {})
        test_result = state.get("test_results", [])
        
        # Format available test commands
        commands_text = "AVAILABLE TEST COMMANDS:\n"
        category_labels = {
            'build_commands': 'Build Commands',
            'level1_commands': 'Level1 (Main Entry) Commands',
            'level2_commands': 'Level2 (Integration) Commands',
            'level3_commands': 'Level3 (Smoke Test) Commands',
            'level4_commands': 'Level4 (Unit Test) Commands',
        }
        
        for key, label in category_labels.items():
            commands = testsuite_commands.get(key, [])
            if commands:
                commands_text += f"\n{label} ({len(commands)}):\n"
                for cmd in commands:
                    if isinstance(cmd, str) and cmd.strip():
                        commands_text += f"  - {cmd.strip()}\n"
        
        # Format test execution summary
        test_results_text = "TEST EXECUTION SUMMARY:\n"
        executed_commands = []  # List to store all test execution history with pass/fail classification and level
        # Collect from test_command_result_history
        test_command_result_history = state.get("test_command_result_history", [])
        if len(test_command_result_history) > 0:
            for history_item in test_command_result_history:
                history_item['status'] = "PASSED" if history_item['result']['returncode'] == 0 else "FAILED"
                executed_commands.append(history_item)

                
        
        if executed_commands:
            passed_count = sum(1 for cmd in executed_commands if cmd["status"] == "PASSED")
            failed_count = sum(1 for cmd in executed_commands if cmd["status"] == "FAILED")
            test_results_text += f"Total executed: {len(executed_commands)}, Passed: {passed_count}, Failed: {failed_count}\n\n"
            
            # Count execution frequency for each unique command
            command_stats = {}  # {(command, level): {"total": count, "passed": count, "failed": count, "last_status": status}}
            for cmd_info in executed_commands:
                command = cmd_info["command"]
                level = cmd_info.get("level", "unknown")
                key = (command, level)
                if key not in command_stats:
                    command_stats[key] = {"total": 0, "passed": 0, "failed": 0, "last_status": None}
                command_stats[key]["total"] += 1
                if cmd_info["status"] == "PASSED":
                    command_stats[key]["passed"] += 1
                else:
                    command_stats[key]["failed"] += 1
                command_stats[key]["last_status"] = cmd_info["status"]
            
            # Group by level for better readability
            level_groups = {}
            for (command, level), stats in command_stats.items():
                if level not in level_groups:
                    level_groups[level] = []
                level_groups[level].append({
                    "command": command,
                    "stats": stats,
                })
            
            for level, commands in level_groups.items():
                test_results_text += f"\nLevel: {level}\n"
                for cmd_info in commands:
                    command = cmd_info["command"]
                    stats = cmd_info["stats"]
                    status_symbol = "✓" if stats["last_status"] == "PASSED" else "✗"
                    exec_count = f" (executed {stats['total']} time{'s' if stats['total'] > 1 else ''}: {stats['passed']} passed, {stats['failed']} failed)"
                    test_results_text += f"  {status_symbol} {command} - {stats['last_status']}{exec_count}\n"
                    # Show last error if failed
                    if stats["last_status"] == "FAILED":
                        # Find the last failed execution's stderr
                        for exec_cmd in reversed(executed_commands):
                            if exec_cmd["command"] == command and exec_cmd.get("level") == level and exec_cmd["status"] == "FAILED":
                                if exec_cmd.get("result", {}).get("stdout"):
                                    stdout_content = exec_cmd["result"]["stdout"]
                                    stdout_preview = stdout_content[-300:].replace("\n", " ") if stdout_content else ""
                                    test_results_text += f"    Last Error: {stdout_preview}...\n"
                                break
        else:
            test_results_text += "No test results available. No tests have been executed yet.\n"
        
        # Build complete prompt text
        prompt_text = f"{commands_text}\n\n{test_results_text}\n\nPlease analyze the test commands and execution history above, then select the next test commands to execute."
        
        # Create prompt template and invoke
        prompt_template = ChatPromptTemplate.from_messages(
            [("system", self.SYS_PROMPT), ("human", "{prompt}")]
        )
        structured_llm = self.model.with_structured_output(TestCommandSelectionOutput)
        model_chain = prompt_template | structured_llm
        
        try:
            response = model_chain.invoke({"prompt": prompt_text})
            selected_command = response.selected_command.strip() if response.selected_command else ""
            level = response.level.strip() if response.level else ""
            
            self._logger.info(f"LLM reasoning: {response.reasoning}")
            self._logger.info(f"Selected command: {selected_command}, Level: {level}")
            
            if not selected_command:
                existing = state.get("selected_test_command", [])
                if isinstance(existing, list):
                    existing = [str(cmd).strip() for cmd in existing if cmd and str(cmd).strip()]
                else:
                    existing = []
                self._logger.warning("LLM returned no command; keeping existing test_command.")
                return {"selected_test_command": existing, "selected_level": None}
            
            return {"selected_test_command": selected_command, "selected_level": level}
            
        except Exception as e:
            self._logger.error(f"Error in LLM-based test selection: {e}")
            existing = state.get("selected_test_command", [])
            if isinstance(existing, list):
                existing = [str(cmd).strip() for cmd in existing if cmd and str(cmd).strip()]
            else:
                existing = []
            self._logger.warning("Falling back to existing test_command due to error.")
            return {"selected_test_command": existing, "selected_level": None}
