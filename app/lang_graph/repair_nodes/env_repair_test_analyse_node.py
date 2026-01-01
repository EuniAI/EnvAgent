"""Node: Analyze errors in test_result_history"""

import functools
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger


class ReadFileInput(BaseModel):
    file_path: str = Field(
        description="The path to the file, which can be an absolute path (e.g., /app/prometheus_setup.sh) or a relative path"
    )


READ_FILE_DESCRIPTION = """\
Read the content of a file at the specified path and add line numbers. The file path is a path within the container (e.g., /app/prometheus_setup.sh).
By default, returns the first 1000 lines to prevent large files from causing excessive context length.
If the file does not exist, an error message will be returned.
"""


class RepairCommandsOutput(BaseModel):
    """Structured output: Contains the list of next repair commands"""

    error_analysis: str = Field(description="Detailed analysis of the error")
    repair_commands: List[str] = Field(
        description="List of specific repair commands to execute next. Each command should be a directly executable shell command using non-interactive flags (e.g., -y/--yes)."
    )


class EnvRepairTestAnalyseNode:
    """Analyze errors in test command execution results and generate repair commands"""

    SYS_PROMPT = """\
You are an environment repair analysis expert. Your task is to analyze the historical results of test command execution, identify the root causes of errors, and generate specific repair command lists.

Input includes:
- TEST COMMAND HISTORY: The last 3 rounds of test command execution history and results
- CURRENT TEST RESULTS: The latest current test results

Your task consists of three parts:

Part 1: Error Analysis
1. Carefully analyze the error information in the current test results
2. Identify root causes (e.g., module not found, command does not exist, missing shared libraries, version conflicts, environment configuration issues, etc.)
3. Analyze why the test failed
4. Provide a detailed error analysis summary

Part 2: Historical Reflection
If TEST COMMAND HISTORY (last 3 rounds) is provided, you need to:
1. Compare the current error with errors from historical rounds
2. Determine if the current error is the same or similar to historical errors
3. If the error keeps appearing (repeated for multiple rounds), it indicates that previous repair strategies may be ineffective
4. In this case, you need to:
   - Reflect on why previous repair methods did not succeed
   - Consider completely different solution approaches (e.g., if apt-get installation failed before, consider compiling from source, using different package managers, modifying environment variables, or adopting containerization solutions, etc.)
   - Avoid repeating methods that have already failed
   - Try innovative, different solution paths

Part 3: Generate Repair Command List
Based on error analysis and historical reflection, generate a repair command list. Requirements:
1. If errors are found to repeat, must adopt a repair strategy different from history
2. Generate multiple specific repair commands, arranged in execution order
3. Each command should be a directly executable shell command
4. Use non-interactive flags (e.g., -y/--yes)
5. Choose appropriate package managers or tools:
   - System packages: apt-get/yum/apk + run apt-get update when needed
   - Python: pip/uv/conda; prioritize using the exact package name indicated in the error
   - Node.js: npm/yarn/pnpm; install missing packages or runtimes (use nvm when needed)
   - Others: cargo/go/gem/composer; or create links/export variables if it's a path issue
6. Prioritize idempotent and safe commands
7. If only one step is needed, the list can contain only one command
8. If multiple steps can be combined into one command (using &&), they can be merged into one command
9. When errors repeat, prioritize alternative solutions rather than repeating the same method

Output requirements:
- error_analysis: Detailed error analysis text (if errors repeat, must include reflection on historical failures and reasons for adopting new strategies)
- repair_commands: Repair command list, each command is a directly executable shell command string, do not include code block markers, quotes, or other explanatory text

Important: Each repair command must be complete and directly executable as a shell command. If errors repeat, must adopt a repair strategy different from history.
"""

    def __init__(self, model: BaseChatModel, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

        # Use structured output
        prompt_template = ChatPromptTemplate.from_messages(
            [("system", self.SYS_PROMPT), ("human", "{prompt}")]
        )
        structured_llm = model.with_structured_output(RepairCommandsOutput)
        self.model = prompt_template | structured_llm

    def _init_tools(self):
        """
        Initialize file reading tools.

        Returns:
          List of StructuredTool instances configured for file reading.
        """
        tools = []

        # Tool: Read file content from container
        read_file_fn = functools.partial(self._read_file_from_container)
        read_file_tool = StructuredTool.from_function(
            func=read_file_fn,
            name="read_file",
            description=READ_FILE_DESCRIPTION,
            args_schema=ReadFileInput,
            response_format="content_and_artifact",
        )
        tools.append(read_file_tool)

        return tools

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
        test_command = state.get("test_commands", [])
        # Use test_results (plural) to match state definition and execute_node return
        test_result = state.get("test_results", {})
        test_command_result_history = state.get("test_command_result_history", [])

        self._logger.info("Analyzing test execution results...")

        # Get the last 3 rounds of history (if exists), excluding the current round
        previous_rounds_text = ""
        if len(test_command_result_history) > 0:
            # Exclude the last entry if it corresponds to the current round
            # Get the last 3 historical items (excluding current round if it exists)
            history_end = len(test_command_result_history)
            # If test_result exists, the last entry in history is likely the current round
            if test_result:
                history_end = len(test_command_result_history) - 1
            
            start_idx = max(0, history_end - 3)
            end_idx = history_end

            if end_idx > start_idx:
                previous_rounds = test_command_result_history[start_idx:end_idx]
                previous_rounds_parts = []

                for idx, history_item in enumerate(previous_rounds):
                    # round_num is the actual index position in history (0-based)
                    round_num = start_idx + idx
                    history_command = history_item.get("command", [])
                    history_result = history_item.get("result", [])
                    history_analysis = history_item.get("analysis", "")

                    # Format history command (may be a list)
                    command_str = ""
                    if isinstance(history_command, list):
                        command_str = "\n".join([str(cmd) for cmd in history_command])
                    else:
                        command_str = str(history_command)

                    # Format history result (may be a list, each result contains results from multiple test commands)
                    result_str_parts = []
                    if isinstance(history_result, list):
                        for res_idx, res in enumerate(history_result):
                            stdout = self._truncate_stdout(res.get("stdout", ""))
                            result_str_parts.append(f"""
                            Test {res_idx + 1}:
                              Command: {res.get("command", "N/A")}
                              Exit Code: {res.get("returncode", "N/A")}
                              Stdout: {stdout}
                            """)
                    else:
                        stdout = self._truncate_stdout(history_result.get("stdout", ""))
                        result_str_parts.append(f"""
                        Exit Code: {history_result.get("returncode", "N/A")}
                        Stdout: {stdout}
                        """)

                    round_text = f"""
                    Round {round_num}:
                    Test Commands:
                    ```
                    {command_str}
                    ```
                    
                    Test Results:
                    {"".join(result_str_parts)}
                    """
                    if history_analysis:
                        round_text += f"  Previous Analysis: {history_analysis}\n"
                    previous_rounds_parts.append(round_text)

                if previous_rounds_parts:
                    previous_rounds_text = """
                    TEST COMMAND HISTORY (Last 3 Rounds):
                    """
                    previous_rounds_text += "\n".join(previous_rounds_parts)

        # Format current test result
        current_test_result_text = ""
        # Handle test_result which can be a dict (from execute_node) or list
        if isinstance(test_result, dict):
            # Single test result as dict
            stdout = self._truncate_stdout(test_result.get("stdout", ""))
            current_test_result_text = f"""
            Command: {test_result.get("command", "N/A")}
            Exit Code: {test_result.get("returncode", "N/A")}
            Stdout: {stdout}
            """
        elif isinstance(test_result, list) and len(test_result) > 0:
            result_parts = []
            for idx, res in enumerate(test_result):
                stdout = self._truncate_stdout(res.get("stdout", ""))
                result_parts.append(f"""
            Test {idx + 1}:
              Command: {res.get("command", "N/A")}
              Exit Code: {res.get("returncode", "N/A")}
              Stdout: {stdout}
            """)
            current_test_result_text = "\n".join(result_parts)
        else:
            current_test_result_text = str(test_result)

        # Format current test command
        current_test_command_text = ""
        if isinstance(test_command, list):
            current_test_command_text = "\n".join([str(cmd) for cmd in test_command])
        else:
            current_test_command_text = str(test_command)

        # Organize query (show latest results, including last 3 rounds of history)
        context_query = """
            <context>
            CURRENT TEST COMMAND:
            ```
            """
        context_query += current_test_command_text
        context_query += """
            ```

            CURRENT TEST RESULTS:
            ```
            """
        context_query += current_test_result_text
        context_query += """
            ```
            """

        # If history information exists, add it to context
        if previous_rounds_text:
            context_query += previous_rounds_text

        context_query += """
            </context>

            """

        # Analyze errors and generate repair command list
        prompt_text = (
            context_query
            + "\nPlease analyze the reasons for the test command execution failure above. If historical round information is provided, compare the current error with historical errors. If errors are found to repeat, reflect on why previous repair strategies were ineffective and adopt a completely different new strategy to resolve them. Finally, generate a repair command list based on the analysis results."
        )

        # Use structured output model
        response = self.model.invoke({"prompt": prompt_text})
        self._logger.debug(f"Model response: {response}")

        # Extract command list
        repair_commands = response.repair_commands if hasattr(response, "repair_commands") else []
        error_analysis_text = response.error_analysis if hasattr(response, "error_analysis") else ""

        self._logger.info(f"Error analysis: {error_analysis_text}")
        self._logger.info(f"Repair command list: {repair_commands}")

        # Convert repair command list to string list (according to state definition, env_repair_command is Sequence[str])
        repair_command_contexts = [cmd.strip() for cmd in repair_commands if cmd.strip()]

        # Update the analysis field of the last entry in test_command_result_history
        test_command_result_history = state.get("test_command_result_history", [])
        if len(test_command_result_history) > 0:
            current_test_history = test_command_result_history[-1].copy()
            current_test_history["analysis"] = error_analysis_text
            test_command_result_history[-1] = current_test_history

        return {
            "env_error_analysis": error_analysis_text,
            "env_repair_command": repair_command_contexts,
            "test_command_result_history": test_command_result_history,
            "test_result": {},  # Clear test_results because current round has completed execution and needs to be re-executed
        }
