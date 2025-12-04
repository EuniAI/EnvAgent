"""Node: Analyze errors in env_implement_result"""

import functools
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from app.container.base_container import BaseContainer

# Extract command from messages (with backward compatibility)
from app.lang_graph.repair_nodes.env_command_utils import extract_command_from_messages
from app.utils.logger_manager import get_thread_logger


class ReadFileInput(BaseModel):
    file_path: str = Field(
        description="Path to the file, can be absolute path (e.g., /app/prometheus_setup.sh) or relative path"
    )


READ_FILE_DESCRIPTION = """\
Read the content of a file at the specified path and add line numbers. The file path is the path inside the container (e.g., /app/prometheus_setup.sh).
By default, returns the first 1000 lines to prevent large files from causing overly long context.
If the file does not exist, an error message will be returned.
"""


class RepairCommandsOutput(BaseModel):
    """Structured output: Contains the list of next repair commands"""

    error_analysis: str = Field(description="Detailed analysis of the error")
    repair_commands: List[str] = Field(
        description="List of specific repair commands to execute next. Each command should be a directly executable shell command using non-interactive flags (e.g., -y/--yes)."
    )
    needs_venv_auto_activate: bool = Field(
        description="Whether virtual environment auto-activation functionality needs to be added. Set to true if the script contains virtual environment activation commands (e.g., `source /opt/venv/bin/activate` or `. /opt/venv/bin/activate`) but lacks logic to write the activation command to ~/.bashrc."
    )


class EnvRepairAnalyseNode:
    """Analyze errors in environment command execution results and generate repair commands"""

    SYS_PROMPT = """\
You are an environment repair analysis expert. Your task is to analyze the results of environment command execution, identify error causes, and generate specific repair command lists.

Input includes:
- ENV IMPLEMENT COMMAND: The executed environment command
- ENV IMPLEMENT OUTPUT: The command's output results (including error information)
- TEST COMMAND: Test commands to run (if any)
- PREVIOUS ROUNDS HISTORY: History of the previous 3 rounds of commands and results (if any)

Your task is divided into three parts:

Part 1: Error Analysis
1. Carefully analyze the error information in ENV IMPLEMENT OUTPUT
2. Identify root causes (e.g., module not found, command does not exist, missing shared libraries, version conflicts, etc.)
3. Analyze why the current command cannot complete environment setup
4. Provide a detailed error analysis summary

Part 2: Historical Reflection
If PREVIOUS ROUNDS HISTORY is provided, you need to:
1. Compare current errors with errors from historical rounds
2. Determine if the current error is the same or similar to historical errors
3. If errors keep appearing (repeated for multiple rounds), it indicates that previous repair strategies may be ineffective
4. In this case, you need to:
   - Reflect on why previous repair methods did not succeed
   - Consider completely different solution approaches (e.g., if apt-get installation failed before, consider compiling from source, using different package managers, modifying environment variables, or adopting containerization solutions, etc.)
   - Avoid repeating methods that have already failed
   - Try innovative, different solution paths

Part 3: Generate Repair Command List
Based on error analysis and historical reflection, generate a repair command list. Requirements:
1. If errors are found to repeat, must adopt repair strategies different from history
2. Generate multiple specific repair commands, arranged in execution order
3. Each command should be a directly executable shell command
4. Use non-interactive flags (e.g., -y/--yes)
5. Choose appropriate package managers or tools:
   - System packages: apt-get/yum/apk + run apt-get update when needed
   - Python: pip/uv/conda; prioritize exact package names mentioned in errors
   - Node.js: npm/yarn/pnpm; install missing packages or runtimes (use nvm when needed)
   - Others: cargo/go/gem/composer; or create links/export variables if it's a path issue
6. Prioritize idempotent and safe commands
7. If only one step is needed, the list can contain only one command
8. If multiple steps can be combined into one command (using && connection), they can be merged into one command
9. When errors repeat, prioritize alternative solutions rather than repeating the same method
10. **Virtual Environment Activation Optimization**: If the script contains virtual environment activation commands (e.g., `source /opt/venv/bin/activate` or `. /opt/venv/bin/activate`), but lacks logic to write the activation command to ~/.bashrc, include in repair commands:
    - Add a function to write the virtual environment activation command to ~/.bashrc for automatic activation
    - Call this function in the script's main function
    - This ensures automatic virtual environment activation every time users enter the container, avoiding the need to manually execute source commands

Output Requirements:
- error_analysis: Detailed error analysis text (if errors repeat, must include reflection on historical failures and reasons for adopting new strategies)
- repair_commands: List of repair commands, each command should be a directly executable shell command string, do not include code block markers, quotes, or other explanatory text
- needs_venv_auto_activate: Boolean value indicating whether virtual environment auto-activation functionality needs to be added. Judgment criteria:
  * If the script contains virtual environment activation commands (e.g., `source /opt/venv/bin/activate` or `. /opt/venv/bin/activate`)
  * But the script lacks logic to write the activation command to ~/.bashrc (no bashrc-related code)
  * Then set to true
  * If the script already has bashrc write logic, or has no virtual environment activation commands, set to false

Important: Each repair command must be complete and directly executable shell commands. If errors repeat, must adopt repair strategies different from history.

Special Attention to Virtual Environment Activation:
- Carefully check the script content in ENV IMPLEMENT COMMAND
- If virtual environment activation commands are found in the script but bashrc auto-activation logic is missing, set needs_venv_auto_activate to true
- Meanwhile, repair_commands can include relevant repair suggestions, explaining that functions need to be added to the script to write activation commands to ~/.bashrc
- This enables automatic virtual environment activation and improves user experience
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

    def __call__(self, state: Dict):
        messages = state.get("env_implement_command_messages", [])
        env_implement_command = extract_command_from_messages(messages, state)

        env_implement_result = state.get("env_implement_result", {})
        env_command_result_history = state.get("env_command_result_history", [])
        test_command = state.get("test_command", "")
        test_result = state.get("test_result", [])

        str_env_implement_command = env_implement_command.get("file_content", "")

        # Get the latest results (the last one)
        latest_env_result = env_implement_result
        latest_test_result = test_result

        self._logger.info("Analyzing environment execution results...")

        # Get history information from the previous 3 rounds (if exists)
        previous_rounds_text = ""
        if len(env_command_result_history) > 1:
            # Get elements from the second-to-last to the fourth-to-last (previous 3 rounds, excluding current round)
            # Current round is the last one, so start from the second-to-last
            start_idx = max(0, len(env_command_result_history) - 4)  # Fourth-to-last
            end_idx = len(env_command_result_history) - 1  # Second-to-last (excluding the last one)

            if end_idx >= start_idx:
                previous_rounds = env_command_result_history[start_idx:end_idx]
                previous_rounds_parts = []

                for idx, history_item in enumerate(previous_rounds):
                    # round_num is the actual index position in history (counting from 0)
                    round_num = start_idx + idx
                    history_command = history_item.get("command", {})
                    history_result = history_item.get("result", {})
                    history_analysis = history_item.get("analysis", "")

                    round_text = f"""
                    Round {round_num}:
                    Command: {history_command.get("file_content", "N/A")}
                    Exit Code: {history_result.get("returncode", "N/A")}
                    Stdout: {history_result.get("stdout", "")}
                    Stderr: {history_result.get("stderr", "")}
                    """
                    if history_analysis:
                        round_text += f"  Previous Analysis: {history_analysis}\n"
                    previous_rounds_parts.append(round_text)

                if previous_rounds_parts:
                    previous_rounds_text = """
                    PREVIOUS ROUNDS HISTORY:
                    """
                    previous_rounds_text += "\n".join(previous_rounds_parts)

        # Organize query (display latest results, including previous 3 rounds history)
        context_query = (
            """
            <context>
            ENV IMPLEMENT COMMAND:
            ```
            """
            + str_env_implement_command
            + """
            ```

            ENV IMPLEMENT OUTPUT (Latest):
            ```
            """
            + str(latest_env_result)
            + """
            ```

            TEST COMMAND:
            ```
            """
            + str(test_command)
            + """
            ```

            TEST OUTPUT (Latest):
            ```
            """
            + str(latest_test_result)
            + """
            ```
        """
        )

        # If historical information exists, add it to context
        if previous_rounds_text:
            context_query += previous_rounds_text

        context_query += """
            </context>

            """

        # Analyze errors and generate repair command list
        prompt_text = (
            context_query
            + "\nPlease analyze the reasons for the above environment command execution failure. If historical round information is provided, compare current errors with historical errors. If errors are found to repeat, reflect on why previous repair strategies were ineffective and adopt completely different new strategies to resolve them. Finally, generate a repair command list based on the analysis results."
        )

        # Use structured output model
        response = self.model.invoke({"prompt": prompt_text})
        self._logger.debug(f"Model response: {response}")

        # Extract command list
        repair_commands = response.repair_commands if hasattr(response, "repair_commands") else []
        error_analysis_text = response.error_analysis if hasattr(response, "error_analysis") else ""
        needs_venv_auto_activate = response.needs_venv_auto_activate if hasattr(response, "needs_venv_auto_activate") else False

        self._logger.info(f"Error analysis: {error_analysis_text}")
        self._logger.info(f"Repair command list: {repair_commands}")
        self._logger.info(f"Needs virtual environment auto-activation: {needs_venv_auto_activate}")

        # Convert repair command list to Context format (according to state definition)

        repair_command_contexts = [cmd.strip() for cmd in repair_commands]

        env_command_result_history = state.get("env_command_result_history", [])
        if len(env_command_result_history) > 0:
            current_env_command_result_history = env_command_result_history[-1]
            current_env_command_result_history["analysis"] = error_analysis_text
            current_env_command_result_history["repair_commands"] = repair_command_contexts
            current_env_command_result_history["needs_venv_auto_activate"] = needs_venv_auto_activate
            env_command_result_history[-1] = current_env_command_result_history

        return {
            "env_error_analysis": error_analysis_text,
            "env_repair_command": repair_command_contexts,
            "needs_venv_auto_activate": needs_venv_auto_activate,
            "env_command_result_history": env_command_result_history,
        }
