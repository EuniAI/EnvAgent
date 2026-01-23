"""Node: Analyze errors and generate a complete global bashfile"""

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


class ErrorAnalysisAndBashfileOutput(BaseModel):
    """Structured output: Contains error analysis and complete bashfile content"""

    error_analysis: str = Field(
        description="Detailed analysis of the error causes and root causes. Focus ONLY on analyzing error causes without generating repair commands."
    )
    bashfile_content: str = Field(
        description="Complete new bash script file content that addresses all identified errors. Must be a complete, executable bash script following best practices."
    )


class EnvRepairGenGlobalBashfileNode:
    """Analyze errors and generate a complete global bashfile"""

    SYS_PROMPT = """\
You are a bash scripting expert and environment repair specialist. Your task is to:
1. Analyze error causes from environment command execution results and test command outputs
2. Generate a complete, new bash script file that addresses all identified errors

Your task has two parts:

Part 1: Error Analysis (ONLY)
Focus ONLY on analyzing the error causes:
1. Carefully analyze the error information in ENV IMPLEMENT OUTPUT
2. If TEST COMMAND OUTPUT is provided, analyze test failures and their root causes
3. Identify root causes (e.g., module not found, command does not exist, missing shared libraries, version conflicts, etc.)
4. Analyze why the current command cannot complete environment setup or why tests are failing
5. Provide a detailed error analysis summary
DO NOT generate repair commands - only analyze the error causes.

Part 2: Generate Complete Bashfile
After analyzing errors, generate a COMPLETE new bash script file based on:
1. The original script content provided in ORIGINAL BASHFILE
2. The error analysis from Part 1
3. The execution results and error information

The new script must:
- Address all identified error causes
- Follow bash scripting best practices
- Include proper error handling (set -e, trap)
- Include color output and logging functions (log, error, warning)
- Organize logic into functions with a main() entry point
- Be idempotent and safe to run multiple times
- Handle Docker container constraints (no sudo, root user, limited system access)
- Use non-interactive flags (e.g., -y/--yes) for all package installations
- Properly handle virtual environment activation if needed (consider adding bashrc auto-activation)
- Install all necessary system packages, runtimes, and dependencies
- Set up environment variables and configurations correctly

Script Format Requirements:
- Must start with #!/bin/bash
- Use set -e to exit on errors
- Include color output and logging functions
- Organize logic into functions, keeping code clear and modular
- Use main function as entry point

IMPORTANT:
- Generate a COMPLETE new bashfile content, not partial modifications
- The new script should solve all the problems identified in the error analysis
- If the original script contains virtual environment activation commands, consider adding bashrc auto-activation logic
- Output the complete bashfile content directly in the response
"""

    def __init__(self, model: BaseChatModel, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

        # Use structured output
        prompt_template = ChatPromptTemplate.from_messages(
            [("system", self.SYS_PROMPT), ("human", "{prompt}")]
        )
        structured_llm = model.with_structured_output(ErrorAnalysisAndBashfileOutput)
        self.model = prompt_template | structured_llm

    def _save_bashfile(self, script_file_path: str, bashfile_content: str) -> bool:
        """Save bashfile content to file system"""
        try:
            file_path = os.path.join(self.container.project_path, script_file_path)
            # Ensure parent directory exists
            parent_dir = os.path.dirname(file_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            
            # Write file content
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(bashfile_content)
            
            self._logger.info(f"Successfully saved bashfile to {script_file_path}")
            return True
        except Exception as e:
            self._logger.error(f"Error saving bashfile to {script_file_path}: {str(e)}")
            return False

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

    def _get_script_relative_path(self, env_command: str) -> str:
        """Extract relative script file path from command"""
        if not env_command or "bash " not in env_command:
            return None

        script_path = env_command.split("bash ")[-1].strip()
        # Remove container path prefix if exists, get relative path
        if script_path.startswith("/app/"):
            script_path = script_path.replace("/app/", "")
        return script_path


    def __call__(self, state: Dict):
        messages = state.get("env_implement_command_messages", [])
        env_command_info = extract_command_from_messages(messages, state)
        env_command = env_command_info.get("command", "")
        env_implement_result = state.get("env_implement_result", {})
        env_command_result_history = state.get("env_command_result_history", [])
        test_command = state.get("test_command", "")
        test_result = state.get("test_results", {})
        test_command_result_history = state.get("test_command_result_history", [])

        str_env_implement_command = env_command_info.get("file_content", "")

        # Get the latest results (the last one)
        latest_env_result = self._truncate_stdout(env_implement_result.get("stdout", ""), max_chars=1500)

        self._logger.info("Analyzing errors and generating complete bashfile...")

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
                    Command: {history_command.get("file_content", "N/A")[:500]}...
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

        # Extract script file path
        script_file_path = self._get_script_relative_path(env_command)
        if not script_file_path:
            self._logger.warning("No script file path found in command")
            return {
                "env_error_analysis": "",
                "env_repair_command": [],
            }

        # Build context query for error analysis and bashfile generation
        context_query = (
            f"""
            <context>
            ORIGINAL SCRIPT FILE PATH: {script_file_path}

            ENV IMPLEMENT COMMAND:
            ```
            {str_env_implement_command}
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

        # Build prompt with original bashfile content
        prompt_text = f"""\
        {context_query}
        
        ORIGINAL BASHFILE:
        ```
        {str_env_implement_command}
        ```
        
        {result_section}
        
        TARGET SCRIPT FILE: {script_file_path}

        Please:
        1. Analyze the error causes from the execution results and test command outputs (Part 1: Error Analysis ONLY)
        2. Based on the original bashfile content, error analysis, execution results, and test outputs, generate a COMPLETE new bashfile content
        3. The new script must be a complete, executable bash script that addresses all identified errors
        4. Output the complete bashfile content directly in your response
        """

        # Use structured output to get error analysis and bashfile content directly
        self._logger.info(f"Analyzing errors and generating complete bashfile: {script_file_path}")
        response = self.model.invoke({"prompt": prompt_text})
        self._logger.debug(f"Model response: {response}")

        # Extract error analysis and bashfile content from structured output
        error_analysis_text = response.error_analysis if hasattr(response, "error_analysis") else ""
        generated_content = response.bashfile_content if hasattr(response, "bashfile_content") else ""

        self._logger.info(f"Error analysis: {error_analysis_text[:200]}...")
        self._logger.info(f"Generated bashfile length: {len(generated_content)} characters")

        # Save the generated bashfile to file system
        if generated_content:
            self._save_bashfile(script_file_path, generated_content)
        else:
            self._logger.warning("No bashfile content generated")

        # Build final command info
        final_env_implement_command = {
            "command": env_command,  # Keep original command format
            "file_content": generated_content,
        }

        # Store command info in message
        completion_msg = store_command_in_message(final_env_implement_command)
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
            current_env_command_result_history["bashfile_generated"] = True
            env_command_result_history[-1] = current_env_command_result_history

        # Update test_command_result_history if test analysis was performed
        test_command_result_history = state.get("test_command_result_history", [])
        if test_result and len(test_command_result_history) > 0:
            current_test_history = test_command_result_history[-1].copy()
            current_test_history["analysis"] = error_analysis_text
            test_command_result_history[-1] = current_test_history

        return {
            "env_error_analysis": error_analysis_text,
            "env_repair_command": [],  # Empty since we're generating complete bashfile, not repair commands
            "env_implement_command": final_env_implement_command,
            "env_implement_command_messages": updated_messages,
            "env_command_result_history": env_command_result_history,
            "test_command_result_history": test_command_result_history,
            "test_result": {},  # Clear test_result to trigger re-execution
        }

