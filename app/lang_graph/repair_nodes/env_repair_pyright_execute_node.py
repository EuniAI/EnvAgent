"""Node: Execute pyright environment quality check (based on pyright)"""

import json
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
        source_script = Path(settings.WORKING_DIRECTORY) / "pyright_env_quality_check.sh"
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

        # Clean up existing output files before running the script
        self._logger.info("Cleaning up existing output files")
        cleanup_cmd = f"rm -f {output_dir}/missing_imports_issues.json {output_dir}/execution.log"
        cleanup_result = self.container.execute_command_with_exit_code(cleanup_cmd)
        if cleanup_result.returncode != 0:
            self._logger.warning(f"Failed to clean up output files: {cleanup_result.stderr}")

        # Run the script
        # Use bash -l to start a login shell, ensuring ~/.bashrc is loaded (including virtual environment activation)
        self._logger.info(f"Executing environment quality check script: {script_path}")
        run_script_cmd = f"bash -l -c '{script_path} {project_path} {output_dir}'"
        script_result = self.container.execute_command_with_exit_code(run_script_cmd)

        # Record script output for debugging and error capture
        self._logger.debug(f"Script execution return code: {script_result.returncode}")
        self._logger.debug(f"Script stdout: {script_result.stdout}")
        if script_result.stderr:
            self._logger.debug(f"Script stderr: {script_result.stderr}")

        # Script generates 2 files: missing_imports_issues.json, execution.log
        # Read missing import issues details file
        read_missing_imports_issues_cmd = f"cat {output_dir}/missing_imports_issues.json 2>/dev/null || echo '{{}}'"
        missing_imports_issues_output = self.container.execute_command_with_exit_code(read_missing_imports_issues_cmd)
        
        # Read execution log for error detection (optional, used as fallback)
        read_execution_log_cmd = f"cat {output_dir}/execution.log 2>/dev/null || echo ''"
        execution_log_output = self.container.execute_command_with_exit_code(read_execution_log_cmd)

        # Parse results
        try:
            # Initialize default values
            issues_count = 0
            missing_imports_issues = []

            # Parse missing import issues details file (this already contains installation errors)
            if missing_imports_issues_output.returncode == 0 and missing_imports_issues_output.stdout.strip():
                try:
                    missing_imports_issues_data = json.loads(missing_imports_issues_output.stdout)
                    missing_imports_issues = missing_imports_issues_data.get("issues", [])
                    # Count issues from missing_imports_issues.json
                    issues_count = len(missing_imports_issues)
                except json.JSONDecodeError as e:
                    self._logger.warning(f"Failed to parse missing_imports_issues.json: {e}")
            
            # If missing_imports_issues is empty, try to extract error information from execution log or script output
            if issues_count == 0 and len(missing_imports_issues) == 0:
                # Combine script output and execution log for error detection
                combined_output = script_result.stdout + "\n" + script_result.stderr
                if execution_log_output.returncode == 0 and execution_log_output.stdout.strip():
                    combined_output += "\n" + execution_log_output.stdout
                
                # Check for common error patterns
                if "externally-managed-environment" in combined_output:
                    missing_imports_issues.append({
                        "file": "pyright_installation",
                        "message": "pyright installation failed: externally-managed-environment error",
                        "rule": "installation_error"
                    })
                    issues_count = 1
                elif "error:" in combined_output.lower() or "Error:" in combined_output:
                    # Extract error information (take first meaningful error block)
                    error_lines = [line for line in combined_output.split("\n") 
                                 if "error" in line.lower() or "Error" in line]
                    if error_lines:
                        error_msg = "Script execution error: " + "; ".join(error_lines[:3])
                        missing_imports_issues.append({
                            "file": "pyright_installation",
                            "message": error_msg,
                            "rule": "installation_error"
                        })
                        issues_count = 1

            self._logger.info(f"Detected {issues_count} issues (including missing import errors and installation errors)")

            # Build result dictionary: update test_result, do not append
            test_result_dict = {
                "command": "pyright_check",
                "returncode": 0 if issues_count == 0 else 1,  # 0 errors means success
                "env_issues": missing_imports_issues,
                "issues_count": issues_count,
            }

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
