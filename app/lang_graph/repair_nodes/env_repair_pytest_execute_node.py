"""Node: Execute pytest environment quality check (based on pytest)"""

import base64
import json
import re
import shutil
from pathlib import Path
from typing import Dict

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger
from app.configuration.config import settings


class EnvRepairPytestExecuteNode:
    """Execute environment installation quality check (using pytest) and return results"""

    def __init__(self, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)
        # Copy pytest script from host to project directory (host operation, not executed in container)
        source_script = Path(settings.PROJECT_DIRECTORY) / "pytest_env_quality_check.sh"
        target_script = self.container.project_path / "pytest_env_quality_check.sh"
        try:
            shutil.copy(source_script, target_script)
            self._logger.info(f"Successfully copied pytest script: {source_script} -> {target_script}")
        except Exception as e:
            error_msg = f"Failed to copy pytest script: {str(e)}"
            self._logger.error(error_msg)
            raise Exception(error_msg)

    def _check_pytest(self) -> bool:
        """Check if pytest is installed in the container"""
        result = self.container.execute_command_with_exit_code(
            "pytest --version", print_output=False
        )
        return result.returncode == 0

    def _parse_pytest_errors(self, pytest_output: str) -> Dict:
        """Parse pytest output and extract structured error information"""
        errors = []
        missing_modules = set()
        
        # Extract error blocks
        for block in re.split(r'_{2,}\s+ERROR collecting\s+', pytest_output)[1:]:
            lines = block.split('\n')
            if not lines:
                continue
            
            test_file = re.sub(r'_{2,}.*$', '', lines[0]).strip() if lines[0] else ""
            if not test_file:
                continue
            
            error_type = error_message = module_error = None
            traceback_lines = []
            
            for line in lines:
                if 'short test summary info' in line:
                    break
                
                # Match error type
                match = re.match(r'^(\w+Error)\s+while\s+importing', line)
                if match:
                    error_type = match.group(1)
                
                # Match error message
                match = re.match(r'^E\s+(.+)$', line)
                if match:
                    error_message = match.group(1).strip()
                    # Extract missing module
                    if "ModuleNotFoundError" in error_message:
                        module_match = re.search(r"No module named ['\"](.+?)['\"]", error_message)
                        if module_match:
                            module_error = module_match.group(1)
                            missing_modules.add(module_error)
                
                if line.strip() and not line.startswith('='):
                    traceback_lines.append(line)
            
            errors.append({
                "test_file": test_file,
                "error_type": error_type,
                "error_message": error_message,
                "traceback": '\n'.join(traceback_lines).strip(),
                "module_error": module_error,
            })
        
        # Extract total error count
        total_match = re.search(r'no tests collected,\s*(\d+)\s+errors?', pytest_output)
        total_errors = int(total_match.group(1)) if total_match else len(errors)
        
        return {
            "errors": errors,
            "total_errors": total_errors,
            "missing_modules": sorted(missing_modules),
        }

    def _format_structured_errors_as_text(self, structured_errors: Dict) -> str:
        """Format structured errors into readable text format"""
        errors = structured_errors.get("errors", [])
        if not errors:
            return ""
        
        total = structured_errors.get('total_errors', len(errors))
        parts = [f"Found {total} error(s) during test collection.\n"]
        
        # Add missing modules summary
        missing_modules = structured_errors.get("missing_modules", [])
        if missing_modules:
            parts.append(f"Missing modules: {', '.join(missing_modules)}\n")
            parts.append(f"Please install: pip install {' '.join(missing_modules)}\n")
        
        parts.append("\n" + "=" * 80 + "\n\n")
        
        # Format each error
        for i, error in enumerate(errors, 1):
            parts.append(f"Error {i}/{total}: {error.get('test_file', 'Unknown file')}\n")
            if error.get("error_type"):
                parts.append(f"  Error Type: {error['error_type']}\n")
            if error.get("module_error"):
                parts.append(f"  Missing Module: {error['module_error']}\n")
            if error.get("error_message"):
                parts.append(f"  Error Message: {error['error_message']}\n")
            
            traceback = error.get("traceback", "").strip()
            if traceback:
                parts.append("\n  Traceback:\n")
                parts.extend(f"    {line}\n" for line in traceback.split('\n') if line.strip())
            
            if i < len(errors):
                parts.append("\n" + "-" * 80 + "\n\n")
        
        return "".join(parts)


    def __call__(self, state: Dict):
        """Execute pytest environment quality check"""
        # Use the working directory in the container as the project path
        project_path = self.container.workdir
        script_path = "/app/pytest_env_quality_check.sh"

        self._logger.info("Starting environment installation quality check (pytest mode)")

        # Add execute permission to the script
        chmod_cmd = f"chmod +x {script_path}"
        chmod_result = self.container.execute_command_with_exit_code(chmod_cmd)
        if chmod_result.returncode != 0:
            self._logger.warning(f"Failed to add execute permission: {chmod_result.stderr}")

        # Run the script
        # Use bash -l to start a login shell, ensuring ~/.bashrc is loaded (including virtual environment activation)
        self._logger.info(f"Executing environment quality check script: {script_path}")
        run_script_cmd = f"bash -l -c '{script_path} {project_path}'"
        script_result = self.container.execute_command_with_exit_code(run_script_cmd, print_output=False, timeout=1800)

        # Record script output for debugging and error capture
        self._logger.debug(f"Script execution return code: {script_result.returncode}")

        try:
            # Get output directly from script result
            pytest_output = script_result.stdout

            self._logger.debug(f"Pytest output: {pytest_output}")

            # Parse results based on return code
            returncode = script_result.returncode
            
            # Check if pytest is not installed (from script output)
            if "pytest command not found" in pytest_output or "Error: pytest command not found" in pytest_output:
                self._logger.error("Pytest is not installed in the environment")
                test_result_dict = {
                    "command": "pytest_check",
                    "returncode": 100,
                    "env_issues": "Pytest is not installed in your environment. Please install the latest version of pytest using `pip install pytest`.",
                    "issues_count": -1,
                }
                test_command_result_history = state.get("test_command_result_history", []) + [
                    {"result": test_result_dict}
                ]
                return {
                    "test_result": test_result_dict,
                    "test_command_result_history": test_command_result_history,
                }
            
            if returncode == 5:
                env_issues = ["No unit tests were detected in this repository, so it passes. Congratulations, you have successfully configured the environment!"]
                issues_count = 0
            elif returncode == 0:
                env_issues = []
                issues_count = 0
            else:
                try:
                    env_issues = self._parse_pytest_errors(pytest_output)
                    # env_issues = self._format_structured_errors_as_text(structured_errors)
                except Exception as e:
                    self._logger.warning(f"Failed to parse pytest errors: {e}")
                
                issues_count = env_issues["total_errors"] if env_issues else -1
            
            test_result_dict = {
                "command": "pytest_check",
                "returncode": returncode,
                "env_issues": env_issues,
                "issues_count": issues_count,
            }

            test_command_result_history = state.get("test_command_result_history", []) + [
                {"result": test_result_dict}
            ]
            return {
                "test_result": test_result_dict,
                "test_command_result_history": test_command_result_history,
            }

        except Exception as e:
            self._logger.error(f"Failed to execute pytest environment quality check: {e}")
            return {
                "test_result": {},
                "test_command_result_history": {},
            }
    