import os
from typing import List, Set

from app.lang_graph.states.testsuite_state import TestsuiteState, save_testsuite_states_to_json
from app.utils.logger_manager import get_thread_logger
from app.container.base_container import BaseContainer

class TestsuitePytestFindWorkflowsNode:
    """
    Node to find pytest test files using pytest --collect-only command.
    This discovers all test files that pytest can collect.

    因为pytest 的collection 命令，需要提前import 环境。
    所以可能不能在env implement之前使用这个进行搜索，而是要在env implement之后运行 testsuite agent。
    所以这个功能需要加在 env repair中。
    """

    def __init__(self, local_path: str, container: BaseContainer):
        """
        Initialize the pytest test finder node.

        Args:
            local_path (str): Local path to the codebase root.
            container (BaseContainer): Container to use for finding pytest tests.
        """
        self.local_path = local_path
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

    def find_pytest_tests(self) -> List[str]:
        """
        Find all pytest test files using pytest --collect-only.

        Returns:
            List[str]: List of paths to found test files.
        """
        found_files: Set[str] = set()

        if not os.path.isdir(self.local_path):
            self._logger.warning(f"The directory {self.local_path} does not exist.")
            return []

        self._logger.info(f"Searching for pytest tests in {self.local_path}...")

        # Run pytest --collect-only inside the container to discover all test files
        # Following Repo2Run's simple approach: use basic pytest collect command
        try:
            # Simple command like Repo2Run: pytest --collect-only -q --disable-warnings
            cmd = "pytest --collect-only -q --disable-warnings"
            result = self.container.execute_command_with_exit_code(cmd, timeout=600)

            # Handle return codes like Repo2Run does
            if result.returncode == 5:
                # pytest returns 5 when no tests are found (standard pytest behavior)
                self._logger.info("No pytest tests were detected in this repository")
                return []
            elif result.returncode != 0:
                # Other non-zero return codes indicate errors
                self._logger.warning(f"pytest returned non-zero exit code: {result.returncode}")
                if result.stdout:
                    self._logger.debug(f"pytest output: {result.stdout}")
                # Still try to parse output in case some tests were collected before error

            output_lines = result.stdout.splitlines()

            for line in output_lines:
                line = line.strip()
                if not line:
                    continue

                file_path = None
                
                # Handle ERROR collecting lines (e.g., "ERROR collecting tests/ffmpeg_handler_test.py")
                if line.startswith("ERROR collecting"):
                    # Extract file path from error line
                    # Format: "ERROR collecting tests/ffmpeg_handler_test.py"
                    parts = line.split("ERROR collecting", 1)
                    if len(parts) > 1:
                        file_path = parts[1].strip()
                        # Remove any trailing characters like underscores or spaces
                        file_path = file_path.split()[0] if file_path.split() else None
                # Handle normal test collection output (e.g., "tests/test_file.py::TestClass::test_method")
                elif '::' in line:
                    file_path = line.split('::')[0]
                # Handle simple file paths
                elif line.endswith('.py') and not line.startswith('=') and not line.startswith('_'):
                    file_path = line

                if not file_path:
                    continue

                # Normalize container path and map to host path
                file_path = os.path.normpath(file_path)
                if os.path.isabs(file_path):
                    # Convert container absolute path (e.g., /app/...) to host path
                    container_root = self.container.workdir.rstrip("/")
                    if file_path.startswith(container_root):
                        rel = file_path[len(container_root):].lstrip("/")
                        host_path = os.path.normpath(os.path.join(self.local_path, rel))
                    else:
                        host_path = file_path
                else:
                    host_path = os.path.normpath(os.path.join(self.local_path, file_path))

                if os.path.isfile(host_path):
                    found_files.add(host_path)
                    self._logger.debug(f"Found pytest test file: {host_path}")

        except Exception as e:
            self._logger.error(f"An error occurred while finding pytest tests: {e}")
            return []

        # Convert set to sorted list for consistent output
        return sorted(list(found_files))

    def __call__(self, state: TestsuiteState):
        """
        Find pytest test files and store their paths in the state.

        Args:
            state (TestsuiteState): Current state.

        Returns:
            dict: Updated state with pytest test file paths.
        """
        self._logger.info("Starting pytest test file discovery process")

        # Find pytest test files
        test_files = self.find_pytest_tests()

        if not test_files:
            self._logger.warning("No pytest test files found")
            state_update = {
                "testsuite_pytest_test_files": [],
            }
        else:
            self._logger.info(f"Found {len(test_files)} pytest test files")
            state_update = {
                "testsuite_pytest_test_files": test_files,
            }
        
        # Save state to JSON (merge state_update into state)
        state_for_saving = {**state, **state_update}
        save_testsuite_states_to_json(state_for_saving, self.local_path)
        
        return state_update

