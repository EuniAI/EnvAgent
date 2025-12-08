"""Node: Execute pyright environment quality check (based on pyright)"""

import json
import re
import shutil
from pathlib import Path
from typing import Dict

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger
from app.configuration.config import settings

class EnvRepairPyrightExecuteNode:
    """Execute environment installation quality check (using pyright) and return results"""

    def __init__(self, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)
        # Copy pyright script from host to project directory (host operation, not executed in container)
        source_script = Path(settings.PROJECT_DIRECTORY) / "pyright_env_quality_check.sh"
        target_script = self.container.project_path / "pyright_env_quality_check.sh"
        try:
            shutil.copy(source_script, target_script)
            self._logger.info(f"Successfully copied pyright script: {source_script} -> {target_script}")
        except Exception as e:
            error_msg = f"Failed to copy pyright script: {str(e)}"
            self._logger.error(error_msg)
            raise Exception(error_msg)

    def __call__(self, state: Dict):
        """Execute pyright environment quality check"""
        # Use the working directory in the container as the project path
        project_path = self.container.workdir
        output_dir = "/app/build_output"
        script_path = "/app/pyright_env_quality_check.sh"

        self._logger.info("Starting environment installation quality check (pyright mode)")


        # Add execute permission to the script
        chmod_cmd = f"chmod +x {script_path}"
        chmod_result = self.container.execute_command_with_exit_code(chmod_cmd)
        if chmod_result.returncode != 0:
            self._logger.warning(f"Failed to add execute permission: {chmod_result.stderr}")

        # Run the script
        # Use bash -l to start a login shell, ensuring ~/.bashrc is loaded (including virtual environment activation)
        self._logger.info(f"Executing environment quality check script: {script_path}")
        run_script_cmd = f"bash -l -c '{script_path} {project_path} {output_dir}'"
        script_result = self.container.execute_command_with_exit_code(run_script_cmd, print_output=False, timeout=1800)

        # Record script output for debugging and error capture
        self._logger.debug(f"Script execution return code: {script_result.returncode}")

        # Parse results from script output
        try:
            # Initialize default values
            issues_count = 0
            missing_imports_issues = []
            pyright_returecode = -1
            
            # 如果出现Running type checking...，则认为pyright安装成功
            if "Running type checking..." in script_result.stdout:
                # 提取 pyright JSON 输出（在 "Running type checking..." 之后的内容）
                try:
                    pyright_json_str = script_result.stdout.split("Running type checking...\n")[1].strip()
                    pyright_result = json.loads(pyright_json_str)
                    general_diagnostics = pyright_result.get("generalDiagnostics", [])
                    missing_imports_issues = [
                        diag for diag in general_diagnostics
                        if diag.get("rule") == "reportMissingImports"
                    ]
                    issues_count = len(missing_imports_issues)
                    pyright_returecode = 0 if issues_count == 0 else 1
                    
                    self._logger.info(f"pyright_result: {json.dumps(missing_imports_issues, indent=2, ensure_ascii=False)}")

                except Exception as e:
                    self._logger.error(f"Failed to extract pyright output: {e}")

            if pyright_returecode != -1:
                test_result_dict = {
                        "command": "pyright_check",
                        "returncode": pyright_returecode,
                        "env_issues": missing_imports_issues,
                        "issues_count": issues_count,
                    }
                self._logger.info(f"Detected {issues_count} issues ")
            else:
                test_result_dict = {
                    "command": "pyright_installation",
                    "returncode": pyright_returecode,
                    "env_issues": script_result.stdout,
                    "issues_count": -1,
                }

                self._logger.info(f"Detected Pyrightinstallation errors")

            # Update history record
            test_command_result_history = state.get("test_command_result_history", []) + [
                {
                    "result": test_result_dict,
                }
            ]
            return {
                "test_result": test_result_dict,
                "test_command_result_history": test_command_result_history,
            }
        except Exception as e:
            self._logger.error(f"Failed to execute pyright environment quality check: {e}")
            return {
                "test_result": {},
                "test_command_result_history": {},
            }
