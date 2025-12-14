import os
import subprocess
from typing import List

from app.lang_graph.states.testsuite_state import TestsuiteState, save_testsuite_states_to_json
from app.utils.logger_manager import get_thread_logger


class TestsuiteCICDFindWorkflowsNode:
    """
    Node to find CI/CD workflow files from .github/workflows directory.
    This follows the logic from ExecutionAgent's base.py find_workflows method.
    """

    def __init__(self, local_path: str):
        """
        Initialize the CI/CD workflow finder node.

        Args:
            local_path (str): Local path to the codebase root.
        """
        self.local_path = local_path
        self._logger, _file_handler = get_thread_logger(__name__)
        # Extended keywords to include common CI/CD workflow patterns
        # Original: ["test", "build", "linux", "unittest", "integration", "deploy"]
        # Added additional keywords to catch more workflow files including CI, validation, and execution patterns
        self.KEYWORDS = [
            "test", "build", "linux", "unittest", "integration", "deploy",
            "ci", "nightly", "check", "compile", "template",
            "workflow", "main", "run", "verify", "validate"
        ]

    def find_workflows(self) -> List[str]:
        """
        Find all test-related workflow files in .github/workflows directory.

        Returns:
            List[str]: List of paths to found workflow files.
        """
        workflow_dir = os.path.join(self.local_path, ".github", "workflows")
        found_files = []

        if not os.path.isdir(workflow_dir):
            self._logger.warning(f"The directory {workflow_dir} does not exist.")
            return found_files

        self._logger.info(f"Searching for test-related workflows in {workflow_dir}...")

        # Find all YAML workflow files in the .github/workflows directory
        try:
            result = subprocess.run(
                ["find", workflow_dir, "-name", "*.yml", "-o", "-name", "*.yaml"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            if result.returncode != 0:
                self._logger.error(f"Error finding files: {result.stderr}")
                return found_files

            # Process the list of found files
            workflow_files = result.stdout.splitlines()

            for file in workflow_files:
                if not file.strip():
                    continue
                # Extract the file name from the full path
                filename = os.path.basename(file).lower()
                # Check if any of the keywords are in the file name
                if any(keyword in filename for keyword in self.KEYWORDS):
                    found_files.append(file)
                    self._logger.debug(f"Found workflow file: {file}")

        except Exception as e:
            self._logger.error(f"An error occurred while finding workflows: {e}")

        return found_files

    def __call__(self, state: TestsuiteState):
        """
        Find CI/CD workflow files and store their paths in the state.

        Args:
            state (TestsuiteState): Current state.

        Returns:
            dict: Updated state with workflow file paths.
        """
        self._logger.info("Starting CI/CD workflow file discovery process")

        # Find workflow files
        workflow_files = self.find_workflows()

        if not workflow_files:
            self._logger.warning("No workflow files found")
            state_update = {
                "testsuite_cicd_workflow_files": [],
            }
        else:
            self._logger.info(f"Found {len(workflow_files)} workflow files")
            state_update = {
                "testsuite_cicd_workflow_files": workflow_files,
            }
        
        # Save state to JSON (merge state_update into state)
        state_for_saving = {**state, **state_update}
        save_testsuite_states_to_json(state_for_saving, self.local_path)
        
        return state_update

