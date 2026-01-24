"""Node: Analyze errors and generate a single repair command"""

import os
from typing import Dict

from langchain.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from app.container.base_container import BaseContainer
from app.lang_graph.repair_nodes.env_command_utils import (
    extract_command_from_messages,
    store_command_in_message,
)
from app.utils.logger_manager import get_thread_logger


class ErrorAnalysisAndCommandOutput(BaseModel):
    """Structured output: Contains error analysis and single command content"""

    error_analysis: str = Field(
        description="Detailed analysis of the error causes and root causes. Focus ONLY on analyzing error causes without generating repair commands."
    )
    command_content: str = Field(
        description="A single, SHORT, and EASY-TO-EXECUTE command that addresses the identified error. Must be a single, concise, executable command. Keep it as simple and brief as possible - minimize chaining with && or ;."
    )


class EnvRepairGenSingleCommandNode:
    """Analyze errors and generate a single repair command"""

    SYS_PROMPT = """\
You are a Linux system expert and environment repair specialist. Your task is to:
1. Analyze error causes from environment command execution results and test command outputs
2. Generate a single repair command that addresses the identified error

Your task has two parts:

Part 1: Error Analysis (ONLY)
Focus ONLY on analyzing the error causes:
1. Carefully analyze the error information in ENV IMPLEMENT OUTPUT
2. If TEST COMMAND OUTPUT is provided, analyze test failures and their root causes
3. Identify root causes (e.g., module not found, command does not exist, missing shared libraries, version conflicts, etc.)
4. Analyze why the current command cannot complete environment setup or why tests are failing
5. Provide a detailed error analysis summary
DO NOT generate repair commands - only analyze the error causes.

Part 2: Generate Single Repair Command
After analyzing errors, generate a SINGLE, SHORT, and EASY-TO-EXECUTE command that can fix the issue:
1. The command should directly address the root cause identified in Part 1
2. The command should be executable in a Docker container environment
3. Use non-interactive flags (e.g., -y/--yes) for all package installations
4. Handle Docker container constraints (no sudo, root user, limited system access)
5. The command should be SHORT and SIMPLE - prefer single operations over complex chaining
6. The command should be idempotent and safe to run multiple times
7. **PRIORITIZE SIMPLICITY**: Generate the shortest, most straightforward command that solves the problem

Command Requirements:
- Must be a single, SHORT command line (minimize chaining with && or ;)
- Must be EASY TO EXECUTE - avoid complex nested commands or long pipelines
- Must include non-interactive flags for package managers
- Must handle errors appropriately (consider using || true if needed)
- Should be specific to the identified error
- Should not require user interaction
- **KEEP IT SHORT**: Prefer simple, direct commands over complex multi-step operations

Common repair patterns:
- Package installation: apt-get update && apt-get install -y <package>
- Python package: pip install <package>
- Create directory: mkdir -p <directory>
- Set environment variable: export VAR=value
- Fix permissions: chmod +x <file>
- Download file: wget -q <url> -O <output>
- Install runtime: curl -fsSL <url> | bash

IMPORTANT:
- Generate a SINGLE, SHORT, and EASY-TO-EXECUTE command that solves the specific problem identified in the error analysis
- The command should be immediately executable and as simple as possible
- Do not generate bash scripts or multi-line solutions - output a single, concise command line
- **SIMPLICITY FIRST**: If multiple operations are needed, chain them with && or ;, but prefer the simplest solution
- **KEEP IT BRIEF**: The shorter and simpler the command, the better - avoid unnecessary complexity
"""

    def __init__(self, model: BaseChatModel, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

        # Use structured output
        prompt_template = ChatPromptTemplate.from_messages(
            [("system", self.SYS_PROMPT), ("human", "{prompt}")]
        )
        structured_llm = model.with_structured_output(ErrorAnalysisAndCommandOutput)
        self.model = prompt_template | structured_llm

    def _truncate_stdout(self, stdout: str, max_chars: int = 1000) -> str:
        """
        Truncate stdout to the last max_chars characters to keep error information.
        
        Args:
            stdout: The stdout string to truncate
            max_chars: Maximum number of characters to keep (default: 1000)
        
        Returns:
            Truncated stdout string (last max_chars characters)
        """
        if not stdout:
            return ""
        if len(stdout) <= max_chars:
            return stdout
        return stdout[-max_chars:]

    def __call__(self, state: Dict):
        messages = state.get("env_implement_command_messages", [])
        env_command_info = extract_command_from_messages(messages, state)
        env_command = env_command_info.get("command", "")
        env_implement_result = state.get("env_implement_result", {})
        env_command_result_history = state.get("env_command_result_history", [])
        test_command = state.get("test_command", "")
        test_result = state.get("test_result", {})  # Fixed: use test_result (singular) not test_results
        test_command_result_history = state.get("test_command_result_history", [])

        str_env_implement_command = env_command_info.get("file_content", "")

        # Get the latest results (the last one)
        latest_env_result = self._truncate_stdout(env_implement_result.get("stdout", ""), max_chars=1500)


        # Get history information from the previous 3 rounds (if exists)
        previous_rounds_text = ""
        if len(env_command_result_history) > 1:
            start_idx = max(0, len(env_command_result_history) - 4)
            end_idx = len(env_command_result_history) - 1

            if end_idx >= start_idx:
                previous_rounds = env_command_result_history[start_idx:end_idx]
                previous_rounds_parts = []

                for idx, history_item in enumerate(previous_rounds):
                    round_num = start_idx + idx
                    history_command = history_item.get("command", {})
                    history_result = history_item.get("result", {})
                    stdout = self._truncate_stdout(history_result.get("stdout", ""))

                    round_text = f"""
                    Round {round_num}:
                    Command: {history_command.get("command", "N/A") if isinstance(history_command, dict) else str(history_command)[:500]}
                    Exit Code: {history_result.get("returncode", "N/A")}
                    Stdout: {stdout}
                    """
                    previous_rounds_parts.append(round_text)

                if previous_rounds_parts:
                    previous_rounds_text = """
                    PREVIOUS ROUNDS HISTORY:
                    """
                    previous_rounds_text += "\n".join(previous_rounds_parts)

        # Get test command history (last 3 rounds)
        test_history_text = ""
        if len(test_command_result_history) > 0:
            start_idx = max(0, len(test_command_result_history) - 3)
            end_idx = len(test_command_result_history)
            
            if end_idx > start_idx:
                test_rounds = test_command_result_history[start_idx:end_idx]
                test_rounds_parts = []
                
                for idx, history_item in enumerate(test_rounds):
                    round_num = start_idx + idx
                    history_command = history_item.get("command", [])
                    history_result = history_item.get("result", [])
                    
                    # Format command
                    command_str = "\n".join([str(cmd) for cmd in history_command]) if isinstance(history_command, list) else str(history_command)
                    
                    # Format result (first 2000 chars of stdout)
                    result_str_parts = []
                    if isinstance(history_result, list):
                        for res_idx, res in enumerate(history_result):
                            stdout = res.get("stdout", "")[:2000]
                            result_str_parts.append(f"""
                            Test {res_idx + 1}: Exit Code: {res.get("returncode", "N/A")}
                            Stdout (first 2000 chars): {stdout}
                            """)
                    else:
                        stdout = history_result.get("stdout", "")[:2000]
                        result_str_parts.append(f"""
                        Exit Code: {history_result.get("returncode", "N/A")}
                        Stdout (first 2000 chars): {stdout}
                        """)
                    
                    round_text = f"""
                    Round {round_num}:
                    Test Commands: {command_str}
                    Test Results: {"".join(result_str_parts)}
                    """
                    test_rounds_parts.append(round_text)
                
                if test_rounds_parts:
                    test_history_text = """
                    TEST COMMAND HISTORY (Last 3 Rounds):
                    """
                    test_history_text += "\n".join(test_rounds_parts)

        # Build context query for error analysis and command generation
        context_query = (
            f"""
            <context>
            ENV IMPLEMENT COMMAND:
            ```
            {str_env_implement_command if str_env_implement_command else env_command}
            ```

            ENV IMPLEMENT OUTPUT (Latest):
            ```
            {str(latest_env_result)}
            ```

            TEST COMMAND:
            ```
            {str(test_command)}
            ```
            """
        )

        # Add current test result if available
        if test_result:
            current_test_output = ""
            if isinstance(test_result, dict):
                stdout = test_result.get("stdout", "")[:2000]
                current_test_output = f"""
                Exit Code: {test_result.get("returncode", "N/A")}
                Stdout (first 2000 chars): {stdout}
                """
            elif isinstance(test_result, list) and len(test_result) > 0:
                test_parts = []
                for idx, res in enumerate(test_result):
                    stdout = res.get("stdout", "")[:2000]
                    test_parts.append(f"""
                Test {idx + 1}: Exit Code: {res.get("returncode", "N/A")}
                Stdout (first 2000 chars): {stdout}
                """)
                current_test_output = "\n".join(test_parts)
            
            if current_test_output:
                context_query += f"""
            
            TEST COMMAND OUTPUT (Current):
            ```
            {current_test_output}
            ```
            """

        if previous_rounds_text:
            context_query += previous_rounds_text

        if test_history_text:
            context_query += test_history_text

        context_query += """
            </context>

            """

        # Build execution result section
        result_section = ""
        if env_implement_result:
            returncode = env_implement_result.get("returncode", "")
            stdout = env_implement_result.get("stdout", "")
            result_section = f"""
            PREVIOUS EXECUTION RESULT:
            Exit Code: {returncode}

            Standard Output:
            ```
            {stdout[:2000]}
            ```

            """

        # Build prompt for error analysis and single command generation
        prompt_text = f"""\
        {context_query}
        
        {result_section}

        Please:
        1. Analyze the error causes from the execution results and test command outputs (Part 1: Error Analysis ONLY)
        2. Based on the error analysis and execution results, generate a SINGLE, SHORT, and EASY-TO-EXECUTE command that can fix the identified issue
        3. The command must be immediately executable, address the root cause, and be as simple and brief as possible
        4. Output the single command directly in your response (minimize chaining - keep it short and simple)
        5. Prioritize simplicity: the shorter and more straightforward the command, the better
        """

        # Use structured output to get error analysis and command directly
        self._logger.info("Analyzing errors and generating single repair command")
        response = self.model.invoke({"prompt": prompt_text})
        self._logger.debug(f"Model response: {response}")

        # Extract error analysis and command from structured output
        error_analysis_text = response.error_analysis if hasattr(response, "error_analysis") else ""
        generated_command = response.command_content if hasattr(response, "command_content") else ""

        self._logger.info(f"Error analysis: {error_analysis_text[:200]}...")
        self._logger.info(f"Generated command: {generated_command}")

        # Build final command info
        final_env_repair_command = {
            "command": generated_command,
            "file_content": "",  # No file content for single command
        }

        # Store command info in message
        completion_msg = store_command_in_message(final_env_repair_command)
        # Update messages with completion message
        if messages:
            updated_messages = messages + [completion_msg]
        else:
            updated_messages = [completion_msg]

        # Update env_command_result_history
        env_command_result_history = state.get("env_command_result_history", [])
        if len(env_command_result_history) > 0:
            current_env_command_result_history = env_command_result_history[-1]
            current_env_command_result_history["analysis"] = error_analysis_text
            current_env_command_result_history["command_generated"] = True
            env_command_result_history[-1] = current_env_command_result_history

        # Update test_command_result_history if test analysis was performed
        test_command_result_history = state.get("test_command_result_history", [])
        if test_result and len(test_command_result_history) > 0:
            current_test_history = test_command_result_history[-1].copy()
            current_test_history["analysis"] = error_analysis_text
            test_command_result_history[-1] = current_test_history

        return {
            "env_error_analysis": error_analysis_text,
            "env_repair_command": [generated_command],  # Return as list with single command
            "env_implement_command_messages": updated_messages,
            "env_command_result_history": env_command_result_history,
            "test_command_result_history": test_command_result_history,
            "test_result": {},  # Clear test_result because current round has completed execution and needs to be re-executed
        }

