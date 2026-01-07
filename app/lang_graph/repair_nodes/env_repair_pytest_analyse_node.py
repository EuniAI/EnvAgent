"""Node: Analyze errors in pytest environment quality check results"""

from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger


class RepairCommandsOutput(BaseModel):
    """Structured output: Contains the list of next repair commands"""

    error_analysis: str = Field(description="Detailed analysis of the errors")
    repair_commands: List[str] = Field(
        description="List of specific repair commands to execute next. Each command should be a directly executable shell command, using non-interactive flags (e.g., -y/--yes)."
    )


class EnvRepairPytestAnalyseNode:
    """Analyze errors in pytest environment quality check results and generate repair commands"""

    SYS_PROMPT = """\
You are an environment repair analysis expert. Your task is to analyze the historical results of pytest environment quality checks, identify the causes of test collection errors (especially missing import errors), and generate specific repair command lists.

Input includes:
- PYTEST CHECK HISTORY: Last 3 rounds of pytest check history and results
- CURRENT PYTEST RESULTS: Current latest pytest check results (structured error information)

Your task is divided into three parts:

Part 1: Error Analysis
1. Carefully analyze the errors in the current pytest check results (env_issues)
2. Focus on missing import errors (ModuleNotFoundError) and identify:
   - List of missing modules/packages (e.g., cv2, numpy)
   - Root causes, with special attention to:
     * Python package not installed in the virtual environment (MOST COMMON)
     * Packages installed in wrong Python environment (system Python vs virtual environment)
     * Virtual environment not activated during installation
     * Incorrect package name
     * Version mismatch
     * Path/PYTHONPATH issues
   - Possible package names corresponding to each missing module (e.g., cv2 -> opencv-python, numpy -> numpy)
3. Special attention to "No module named pytest" error:
   - This indicates pytest is not installed in the virtual environment where the script runs
   - May also indicate packages were installed in a different Python environment than where pytest executes
4. Analyze other types of errors if present:
   - ImportError with "cannot open shared object file" (e.g., libEGL.so.1, libQt6Core.so.6):
     * This indicates missing system-level libraries, NOT Python packages
     * Common for GUI libraries (PySide6, PyQt6, tkinter) that require system dependencies
     * Solution: Install system packages via apt-get/yum/apk (e.g., libegl1, libqt6core6, etc.)
   - SyntaxError, AttributeError, etc.
5. Provide a detailed error analysis summary, including:
   - List of missing modules/packages
   - List of missing system libraries (if any)
   - Error types and their frequencies
   - Affected test files
   - Package managers that may be needed to install these packages
   - Whether virtual environment activation issues are suspected
   - Whether system-level dependencies are needed

Part 2: Historical Reflection
If PYTEST CHECK HISTORY (last 3 rounds) is provided, you need to:
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
   - For ImportError with "cannot open shared object file" (e.g., libEGL.so.1, libQt6Core.so.6):
     * These are system library dependencies, NOT Python packages
     * Install system packages: apt-get install libegl1 libqt6core6 libqt6gui6 (for Qt/PySide6)
     * Common system libraries needed:
       - Qt/PySide6: libegl1, libqt6core6, libqt6gui6, libqt6widgets6, libxcb-xinerama0
       - OpenGL: libgl1-mesa-glx, libglib2.0-0
       - X11: libx11-6, libxext6, libxrender1
     * Always run apt-get update before installing system packages
   - If package name is uncertain, try common variants (e.g., cv2 -> opencv-python, opencv-contrib-python)
6. Prioritize idempotent and safe commands
7. If only one step is needed, the list can contain only one command
8. If multiple steps can be combined into one command (using && connection), they can be merged into one command
9. When errors repeat, prioritize alternative solutions rather than repeating the same method
10. For missing imports:
    - If ModuleNotFoundError: Install the corresponding Python package in virtual environment
    - If ImportError with "cannot open shared object file": Install the required system libraries (NOT Python packages)
    - If that fails, consider installing system packages or setting environment variables

11. **CRITICAL: Virtual Environment Installation Strategy**
    - If the error shows "No module named pytest" or similar issues where packages seem installed but pytest cannot find them, this often indicates packages were installed in the wrong Python environment
    - ALWAYS ensure packages are installed in the virtual environment where pytest runs:
      * Method 1 (Recommended): Activate virtual environment first, then install
        ```bash
        source /app/.venv/bin/activate && pip install <package>
        ```
        Or use the virtual environment's Python directly:
        ```bash
        /app/.venv/bin/python3 -m pip install <package>
        ```
      * Method 2: If virtual environment path is known (e.g., /app/.venv), use it explicitly:
        ```bash
        /app/.venv/bin/pip install <package>
        ```
    - Verify the installation location by checking which Python/pip is being used:
      * Before installation: `which python` or `which pip` should point to virtual environment
      * After installation: Verify with `/app/.venv/bin/python3 -c "import <module>"`
    - If pytest itself is missing, ensure pytest is also installed in the virtual environment:
      ```bash
      source /app/.venv/bin/activate && pip install pytest
      ```
      Or: `/app/.venv/bin/python3 -m pip install pytest`
    - Common virtual environment paths to check/use: /app/.venv, /app/venv, /opt/venv, $HOME/venv

Output requirements:
- error_analysis: Detailed error analysis text (if errors repeat, must include reflection on historical failures and reasons for adopting new strategies)
- repair_commands: List of repair commands, each command is a directly executable shell command string, do not include code block markers, quotes, or other explanatory text

Important: Each repair command must be complete and directly executable shell commands. If errors repeat, must adopt a repair strategy different from history.
"""

    def __init__(self, model: BaseChatModel, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)
        prompt_template = ChatPromptTemplate.from_messages(
            [("system", self.SYS_PROMPT), ("human", "{prompt}")]
        )
        structured_llm = model.with_structured_output(RepairCommandsOutput)
        self.model = prompt_template | structured_llm

    def _format_env_issues(self, env_issues) -> str:
        """Format env_issues into readable text"""
        if isinstance(env_issues, dict):
            errors = env_issues.get("errors", [])
            missing_modules = env_issues.get("missing_modules", [])
            total_errors = env_issues.get("total_errors", 0)
            
            if total_errors == 0:
                return "No errors found or check passed\n"
            
            parts = [f"Total errors: {total_errors}\n"]
            if missing_modules:
                parts.append(f"Missing modules: {', '.join(missing_modules)}\n")
            for error in errors:
                parts.append(f"""
                    Test File: {error.get('test_file', 'Unknown')}
                    Error Type: {error.get('error_type', 'Unknown')}
                    Missing Module: {error.get('module_error') or 'N/A'}
                    Error Message: {error.get('error_message', '')}
                    """)
            return "\n".join(parts)
        
        if isinstance(env_issues, list):
            return "\n".join(str(msg) for msg in env_issues) + "\n" if env_issues else "No errors found\n"
        if isinstance(env_issues, str):
            return f"Error message: {env_issues}\n"
        return f"Unknown format: {type(env_issues).__name__}\n"


    def __call__(self, state: Dict):
        test_result = state.get("test_result", {})
        test_command_result_history = state.get("test_command_result_history", [])

        self._logger.info("Analyzing pytest environment quality check results...")

        # Format current results
        current_env_issues = test_result.get("env_issues", {}) if isinstance(test_result, dict) else {}
        current_result_text = self._format_env_issues(current_env_issues)

        # Format historical results (last 3 rounds)
        previous_rounds_text = ""
        if len(test_command_result_history) > 1:
            start_idx = max(0, len(test_command_result_history) - 4)
            end_idx = len(test_command_result_history) - 1
            
            if end_idx > start_idx:
                previous_rounds = test_command_result_history[start_idx:end_idx]
                rounds_parts = []
                
                for idx, history_item in enumerate(previous_rounds):
                    round_num = start_idx + idx
                    history_result = history_item.get("result", {})
                    if isinstance(history_result, dict):
                        history_env_issues = history_result.get("env_issues", {})
                        history_analysis = history_item.get("analysis", "")
                        formatted = self._format_env_issues(history_env_issues)
                        rounds_parts.append(f"""
                    Round {round_num}:
                    {formatted}
                    Previous Analysis: {history_analysis}
                    """)
                
                if rounds_parts:
                    previous_rounds_text = "PYTEST CHECK HISTORY (Last 3 Rounds):\n" + "\n".join(rounds_parts)

        # Build context query
        context_query = f"""
            <context>
            CURRENT PYTEST CHECK RESULTS:
            ```
            {current_result_text}
            ```
            """
        if previous_rounds_text:
            context_query += previous_rounds_text
        context_query += """
            </context>

            Please analyze the reasons for the above pytest environment quality check failures. Focus on missing import errors (ModuleNotFoundError). If historical round information is provided, compare current errors with historical errors. If errors are found to repeat, reflect on why previous repair strategies were ineffective and adopt completely different new strategies to resolve them. Finally, generate a repair command list based on the analysis results.
            """

        # Get model response
        response = self.model.invoke({"prompt": context_query})
        self._logger.debug(f"Model response: {response}")

        repair_commands = getattr(response, "repair_commands", [])
        error_analysis_text = getattr(response, "error_analysis", "")

        self._logger.info(f"Error analysis: {error_analysis_text}")
        self._logger.info(f"Repair command list: {repair_commands}")

        # Update history with analysis
        if test_command_result_history:
            test_command_result_history[-1] = {
                **test_command_result_history[-1],
                "analysis": error_analysis_text
            }

        return {
            "env_error_analysis": error_analysis_text,
            "env_repair_command": [cmd.strip() for cmd in repair_commands if cmd.strip()],
            "test_command_result_history": test_command_result_history,
            "test_result": {},
        }

