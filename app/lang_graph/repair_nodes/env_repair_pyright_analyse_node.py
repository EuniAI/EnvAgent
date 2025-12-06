"""Node: Analyze errors in pyright environment quality check results"""

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
        description="Path to the file, can be an absolute path (e.g., /app/prometheus_setup.sh) or a relative path"
    )


READ_FILE_DESCRIPTION = """\
Read the content of the file at the specified path and add line numbers. The file path is a path within the container (e.g., /app/prometheus_setup.sh).
By default, returns the first 1000 lines to prevent large files from causing excessive context.
If the file does not exist, an error message will be returned.
"""


class RepairCommandsOutput(BaseModel):
    """Structured output: Contains the list of next repair commands"""

    error_analysis: str = Field(description="Detailed analysis of the errors")
    repair_commands: List[str] = Field(
        description="List of specific repair commands to execute next. Each command should be a directly executable shell command, using non-interactive flags (e.g., -y/--yes)."
    )


class EnvRepairPyrightAnalyseNode:
    """Analyze errors in pyright environment quality check results and generate repair commands"""

    SYS_PROMPT = """\
You are an environment repair analysis expert. Your task is to analyze the historical results of pyright environment quality checks, identify the causes of missing import errors, and generate specific repair command lists.

Input includes:
- PYRIGHT CHECK HISTORY: Last 3 rounds of pyright check history and results
- CURRENT PYRIGHT RESULTS: Current latest pyright check results

Your task is divided into three parts:

Part 1: Error Analysis
1. Carefully analyze the missing import errors (env_issues) in the current pyright check results
2. Identify the root causes of each missing import error (e.g., Python package not installed, incorrect package name, version mismatch, path issues, etc.)
3. Analyze why these imports fail
4. Provide a detailed error analysis summary, including:
   - List of missing modules/packages
   - Possible package names corresponding to each missing module
   - Package managers that may be needed to install these packages

Part 2: Historical Reflection
If PYRIGHT CHECK HISTORY (last 3 rounds) is provided, you need to:
1. Compare current errors with errors from historical rounds
2. Determine if current errors are the same or similar to historical errors (e.g., the same module is always missing)
3. If errors persist (repeated across multiple rounds), it indicates that previous repair strategies may be ineffective
4. In this case, you need to:
   - Reflect on why previous repair methods did not succeed (e.g., incorrect package name, need for different package manager, need for system-level dependencies, etc.)
   - Consider completely different solution approaches (e.g., if pip installation failed before, consider using apt-get to install system packages, using different package names, installing from source, modifying PYTHONPATH, etc.)
   - Avoid repeating methods that have already failed
   - Try innovative, different solution paths

Part 3: Generate Repair Command List
Based on error analysis and historical reflection, generate a repair command list. Requirements:
1. If errors are found to repeat, must adopt a repair strategy different from history
2. Generate multiple specific repair commands, arranged in execution order
3. Each command should be a directly executable shell command
4. Use non-interactive flags (e.g., -y/--yes)
5. Choose appropriate package managers or tools:
   - Python packages: pip/uv/conda; prioritize using the exact package name indicated in the error
   - System packages (if Python packages require system dependencies): apt-get/yum/apk + run apt-get update when needed
   - If package name is uncertain, try common variants (e.g., python3-xxx, python-xxx)
6. Prioritize idempotent and safe commands
7. If only one step is needed, the list can contain only one command
8. If multiple steps can be combined into one command (using && connection), they can be merged into one command
9. When errors repeat, prioritize alternative solutions rather than repeating the same method
10. For missing imports, prioritize installing the corresponding Python package; if that fails, consider installing system packages or setting environment variables

Output requirements:
- error_analysis: Detailed error analysis text (if errors repeat, must include reflection on historical failures and reasons for adopting new strategies)
- repair_commands: List of repair commands, each command is a directly executable shell command string, do not include code block markers, quotes, or other explanatory text

Important: Each repair command must be complete and directly executable shell commands. If errors repeat, must adopt a repair strategy different from history.
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


    def __call__(self, state: Dict):
        test_result = state.get("test_result", {})
        test_command_result_history = state.get("test_command_result_history", [])

        self._logger.info("Analyzing pyright environment quality check results...")

        # Get last 3 rounds of historical information (if exists)
        previous_rounds_text = ""
        if len(test_command_result_history) > 0:
            # Get last 3 historical items (excluding current round), current round is the last one, so start from the 4th from the end
            start_idx = max(0, len(test_command_result_history) - 4)
            end_idx = len(test_command_result_history) - 1

            if end_idx > start_idx:
                previous_rounds = test_command_result_history[start_idx:end_idx]
                previous_rounds_parts = []

                for idx, history_item in enumerate(previous_rounds):
                    # round_num is the actual index position in history (counting from 0)
                    round_num = start_idx + idx
                    history_result_dict = history_item.get("result", {})
                    if not isinstance(history_result_dict, dict):
                        history_result_dict = {}
                    history_result = history_result_dict.get("env_issues", [])  # 'env_issues' : 'file','message'
                    history_analysis = history_item.get("analysis", "")

                    # Format historical results (pyright check results)
                    result_str_parts = []
                    if isinstance(history_result, list):
                        if len(history_result) > 0:
                            for issue in history_result:
                                if isinstance(issue, dict):
                                    file = issue.get("file", "")
                                    result = issue.get("message", "")
                                    result_str_parts.append(f"""
                                File: {file}
                                result: {result}
                                """)
                        else:
                            # If historical result is empty, add prompt information
                            result_str_parts.append("""
                                File: (No errors)
                                result: Previous round check found no errors or check failed
                                """)
                    else:
                        # If history_result is not a list, add error information
                        result_str_parts.append(f"""
                                File: (Data format error)
                                result: Historical result format is incorrect: {type(history_result).__name__}
                                """)

                    previous_rounds_parts.append(f"""
                    Round {round_num}:
                    {"".join(result_str_parts)}
                    Previous Analysis: {history_analysis}
                    """)

                if len(previous_rounds_parts) > 0:
                    previous_rounds_text = """
                    PYRIGHT CHECK HISTORY (Last 3 Rounds):
                    """
                    previous_rounds_text += "\n".join(previous_rounds_parts)

        # Format current pyright check results
        current_pyright_result_text = ""
        if isinstance(test_result, dict):
            current_env_issues = test_result.get("env_issues", [])
            result_str_parts = []
            if isinstance(current_env_issues, list) and len(current_env_issues) > 0:
                for issue in current_env_issues:
                    if isinstance(issue, dict):
                        file = issue.get("file", "")
                        result = issue.get("message", "")
                        result_str_parts.append(f"""
                    File: {file}
                    result: {result}
                    """)
            elif isinstance(current_env_issues, list) and len(current_env_issues) == 0:
                # If current result is empty, add prompt information
                result_str_parts.append("""
                    File: (No errors)
                    result: Current check found no errors or check failed
                    """)
            else:
                # If format is incorrect, add error information
                result_str_parts.append(f"""
                    File: (Data format error)
                    result: Current result format is incorrect: {type(current_env_issues).__name__}
                    """)
            current_pyright_result_text = "\n".join(result_str_parts)
        else:
            # If test_result is not a dictionary, add error information
            current_pyright_result_text = f"""
                    File: (Data format error)
                    result: test_result is not a dictionary type: {type(test_result).__name__}
                    """

        # Organize query (show latest results, including last 3 rounds of history)
        context_query = """
            <context>
            CURRENT PYRIGHT CHECK RESULTS:
            ```
            """
        context_query += current_pyright_result_text
        context_query += """
            ```
            """

        # If historical information exists, add it to context
        if previous_rounds_text:
            context_query += previous_rounds_text

        context_query += """
            </context>

            """

        # Analyze errors and generate repair command list
        prompt_text = (
            context_query
            + "\nPlease analyze the reasons for the above pyright environment quality check failures. Focus on missing import errors (Missing Import Issues). If historical round information is provided, compare current errors with historical errors. If errors are found to repeat, reflect on why previous repair strategies were ineffective and adopt completely different new strategies to resolve them. Finally, generate a repair command list based on the analysis results."
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

        # Update the analysis of the last entry in test_command_result_history
        test_command_result_history = state.get("test_command_result_history", [])
        if len(test_command_result_history) > 0:
            current_test_history = test_command_result_history[-1].copy()
            current_test_history["analysis"] = error_analysis_text
            test_command_result_history[-1] = current_test_history

        return {
            "env_error_analysis": error_analysis_text,
            "env_repair_command": repair_command_contexts,
            "test_command_result_history": test_command_result_history,
            "test_result": {},  # Clear test_result because current round has completed execution and needs to be re-executed

        }

