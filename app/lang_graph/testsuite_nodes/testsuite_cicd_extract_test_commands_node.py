import os
from typing import List, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.lang_graph.states.testsuite_state import TestsuiteState
from app.utils.logger_manager import get_thread_logger


class CommandExtractionOutput(BaseModel):
    """Structured output model for extracted commands from workflow analysis."""
    
    commands: Sequence[str] = Field(
        description="List of executable commands extracted from the workflow analysis. "
        "Include only actual shell commands that can be executed, prioritizing test execution commands. "
        "Exclude explanations, comments, and non-executable text."
    )


class TestsuiteCICDExtractTestCommandsNode:
    """
    Node to extract test commands directly from CI/CD workflow files.
    Uses LLM with structured output to extract executable commands from GitHub Actions workflow YAML files.
    """

    def __init__(self, model: BaseChatModel, local_path: str):
        """
        Initialize the CI/CD test command extraction node.

        Args:
            model (BaseChatModel): The LLM used for workflow analysis.
            local_path (str): Local path to the codebase root.
        """
        self.local_path = local_path
        self._logger, _file_handler = get_thread_logger(__name__)
        
        # Prompt for extracting structured commands directly from workflow files
        direct_command_extraction_prompt = (
            "You are a command extraction specialist. Your task is to extract executable commands "
            "directly from GitHub Actions workflow YAML files. Extract ONLY the actual commands that can be executed in a shell, "
            "prioritizing test execution commands. Look for commands in 'run' steps, script sections, and any executable code. "
            "Include build commands, test commands, installation commands, and setup commands. "
            "Exclude explanations, comments, and non-executable text. Return a list of clean, executable commands."
        )
        
        self.direct_command_extraction_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", direct_command_extraction_prompt),
                ("human", "Extract all executable test and build commands from the following GitHub Actions workflow file:\n\n# file: {workflow_file}\n```yaml\n{workflow_content}\n```\n\nFocus on commands that can be directly executed in a shell environment. Extract commands from 'run' steps, scripts, and any executable code blocks."),
            ]
        )
        # Use structured output to get command list directly from workflow
        structured_llm = model.with_structured_output(CommandExtractionOutput)
        self.direct_command_extraction_model = self.direct_command_extraction_prompt | structured_llm

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

    def extract_commands_directly_from_workflow(self, workflow_path: str, content: str) -> List[str]:
        """
        Extract executable commands directly from workflow file using structured output.
        
        Args:
            workflow_path (str): Path to the workflow file.
            content (str): Content of the workflow file.
            
        Returns:
            List[str]: List of extracted executable commands.
        """
        if not content:
            return []
        
        wp = workflow_path.split("/")[-1] if "/" in workflow_path else workflow_path
        
        try:
            # Use structured output to get commands directly from workflow
            result = self.direct_command_extraction_model.invoke({
                "workflow_file": wp,
                "workflow_content": content
            })
            commands = list(result.commands) if result.commands else []
            
            # Clean and validate commands
            cleaned_commands = []
            seen = set()
            for cmd in commands:
                if not cmd or not isinstance(cmd, str):
                    continue
                # Remove extra whitespace
                cmd = ' '.join(cmd.split())
                # Skip very short commands (likely false positives)
                if len(cmd) < 5:
                    continue
                # Normalize and deduplicate
                cmd_lower = cmd.lower()
                if cmd_lower not in seen:
                    seen.add(cmd_lower)
                    cleaned_commands.append(cmd)
            
            self._logger.debug(f"Extracted {len(cleaned_commands)} commands directly from workflow using structured output")
            return cleaned_commands
            
        except Exception as e:
            self._logger.error(f"Error extracting commands directly from workflow {workflow_path}: {e}")
            return []

    def __call__(self, state: TestsuiteState):
        """
        Read workflow files and extract test commands directly using structured output.

        Args:
            state (TestsuiteState): Current state containing workflow file paths.

        Returns:
            dict: Updated state with workflow contents and extracted test commands.
        """
        self._logger.info("Starting CI/CD test command extraction process")

        workflow_files = state.get("testsuite_workflow_files", [])
        
        if not workflow_files:
            self._logger.warning("No workflow files found in state, skipping extraction")
            return {
                "testsuite_workflow_contents": {},
                "testsuite_extracted_commands": [],
            }

        # Read content and extract test commands for each workflow file
        workflow_contents = {}
        extracted_commands = []  # List of all extracted commands across all workflows
        
        for workflow_path in workflow_files:
            if not workflow_path or not os.path.exists(workflow_path):
                self._logger.warning(f"Workflow file not found: {workflow_path}")
                continue
                
            # Read workflow content
            content = self.read_workflow_content(workflow_path)
            if not content:
                continue
                
            # Store relative path as key for easier reference
            relative_path = os.path.relpath(workflow_path, self.local_path)
            workflow_contents[relative_path] = content
            self._logger.debug(f"Read workflow content from {relative_path} ({len(content)} chars)")
            
            # Extract commands directly from workflow file using structured output
            self._logger.info(f"Extracting test commands directly from {relative_path}...")
            commands = self.extract_commands_directly_from_workflow(workflow_path, content)
            if commands:
                self._logger.info(f"Extracted {len(commands)} executable commands from {relative_path}")
                extracted_commands.extend(commands)
            else:
                self._logger.warning(f"No commands extracted from {relative_path}")

        self._logger.info(
            f"Processed {len(workflow_files)} workflow files, "
            f"total {len(extracted_commands)} executable commands found"
        )

        return {
            "testsuite_workflow_contents": workflow_contents,
            "testsuite_extracted_commands": extracted_commands,
        }

