import os
import subprocess
from typing import List

from app.lang_graph.states.testsuite_state import TestsuiteState
from app.utils.logger_manager import get_thread_logger


class TestsuiteCICDWorkflowNode:
    """
    Node to find and extract CI/CD workflow files from .github/workflows directory.
    This follows the logic from ExecutionAgent's base.py find_workflows and workflow_to_script methods,
    but without using LLM for analysis - only file operations.
    """

    def __init__(self, local_path: str):
        """
        Initialize the CI/CD workflow node.

        Args:
            local_path (str): Local path to the codebase root.
        """
        self.local_path = local_path
        self._logger, _file_handler = get_thread_logger(__name__)
        self.KEYWORDS = ["test", "build", "linux", "unittest", "integration", "deploy"]

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

    def read_workflow_content(self, workflow_path: str) -> str:
        """
        Read the content of a workflow file.

        Args:
            workflow_path (str): Path to the workflow file.

        Returns:
            str: Content of the workflow file, or empty string if error.
        """
        try:
            with open(workflow_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content
        except Exception as e:
            self._logger.error(f"Error reading workflow file {workflow_path}: {e}")
            return ""

    def __call__(self, state: TestsuiteState):
        """
        Find and read CI/CD workflow files, storing their content in the state.

        Args:
            state (TestsuiteState): Current state.

        Returns:
            dict: Updated state with workflow information.
        """
        self._logger.info("Starting CI/CD workflow discovery process")

        # Find workflow files
        workflow_files = self.find_workflows()

        if not workflow_files:
            self._logger.warning("No workflow files found")
            return {
                "testsuite_workflow_files": [],
                "testsuite_workflow_contents": {},
            }

        # Read content of each workflow file
        workflow_contents = {}
        for workflow_path in workflow_files:
            content = self.read_workflow_content(workflow_path)
            if content:
                # Store relative path as key for easier reference
                relative_path = os.path.relpath(workflow_path, self.local_path)
                workflow_contents[relative_path] = content
                self._logger.debug(f"Read workflow content from {relative_path} ({len(content)} chars)")

        self._logger.info(f"Found {len(workflow_files)} workflow files, successfully read {len(workflow_contents)}")

        return {
            "testsuite_workflow_files": workflow_files,
            "testsuite_workflow_contents": workflow_contents,
        }

