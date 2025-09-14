import functools
import logging
import re
import threading
from pathlib import Path

from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.states.env_implement_state import EnvImplementState
from app.tools import file_operation
from app.utils.lang_graph_util import get_last_message_content
from app.utils.logger_manager import get_thread_logger

class EnvImplementFileNode:
    SYS_PROMPT = """\
    You are a Dockerfile manager. Your task is to save the provided Dockerfile in the project. You should:

    1. Examine the project structure to identify the best location for the Dockerfile (typically at the project root)
    2. Use the create_file tool to save the Dockerfile in a SINGLE new file named "Dockerfile" (without extension)
    3. If a Dockerfile already exists, you may need to use a different name like "Dockerfile.new" or "Dockerfile.generated"
    4. After creating the file, return its relative path

    Tools available:
    - read_file: Read the content of a file
    - create_file: Create a new SINGLE file with specified content

    If create_file fails because there is already a file with that name, use another name.
    Respond with the created file's relative path.
    """

    HUMAN_PROMPT = """\
    Save this Dockerfile in the project:
    {dockerfile_content}

    Current project structure:
    {project_structure}
    """

    def __init__(self, model: BaseChatModel, kg: KnowledgeGraph, local_path: str):
        self.kg = kg
        self.tools = self._init_tools(local_path)
        self.model_with_tools = model.bind_tools(self.tools)
        self.system_prompt = SystemMessage(self.SYS_PROMPT)
        self._logger, _file_handler = get_thread_logger(__name__)

    def _init_tools(self, root_path: str):
        """Initializes file operation tools with the given root path.

        Args:
          root_path: Base directory path for all file operations.

        Returns:
          List of StructuredTool instances configured for file operations.
        """
        tools = []

        read_file_fn = functools.partial(file_operation.read_file, root_path=root_path)
        read_file_tool = StructuredTool.from_function(
            func=read_file_fn,
            name=file_operation.read_file.__name__,
            description=file_operation.READ_FILE_DESCRIPTION,
            args_schema=file_operation.ReadFileInput,
        )
        tools.append(read_file_tool)

        create_file_fn = functools.partial(file_operation.create_file, root_path=root_path)
        create_file_tool = StructuredTool.from_function(
            func=create_file_fn,
            name=file_operation.create_file.__name__,
            description=file_operation.CREATE_FILE_DESCRIPTION,
            args_schema=file_operation.CreateFileInput,
        )
        tools.append(create_file_tool)

        return tools

    def format_human_message(self, state: EnvImplementState) -> HumanMessage:
        return HumanMessage(
            self.HUMAN_PROMPT.format(
                dockerfile_content=get_last_message_content(
                    state["env_implement_write_messages"]
                ),
                project_structure=self.kg.get_file_tree(),
            )
        )

    def _extract_file_path_from_messages(self, messages) -> str:
        """Extract the file path from tool call response messages.
        
        Args:
            messages: List of messages that may contain ToolMessage responses
            
        Returns:
            str: The relative path of the created file, or empty string if not found
        """
        for message in messages:
            # Check if it's a ToolMessage (tool execution result)
            if hasattr(message, 'content') and hasattr(message, 'tool_call_id'):
                # Look for patterns like "The file {path} has been created"
                pattern = r"The file\s+([^\s]+)\s+has been created"
                match = re.search(pattern, message.content)
                if match:
                    return match.group(1)
                
                # Look for patterns like "Dockerfile" or "Dockerfile.new" in the content
                pattern = r"(Dockerfile(?:\.\w+)?)"
                match = re.search(pattern, message.content)
                if match:
                    return match.group(1)
        
        return ""

    def __call__(self, state: EnvImplementState):
        message_history = [self.system_prompt, self.format_human_message(state)] + state[
            "env_implement_file_messages"
        ]

        response = self.model_with_tools.invoke(message_history)
        self._logger.debug(response)
        
        # Prepare the return dictionary
        result = {"env_implement_file_messages": [response]}
        
        # Check if there are any tool call responses in the current messages
        # (This happens when we're called after tool execution)
        current_messages = state.get("env_implement_file_messages", [])
        file_path = self._extract_file_path_from_messages(current_messages)
        
        # If we found a file path, add it to the state
        if file_path:
            # Convert relative path to Path object for dockerfile_path
            result["dockerfile_path"] = Path(file_path)
            self._logger.info(f"Extracted Dockerfile path: {file_path}")
        else:
            self._logger.debug("No file path found in current messages")
        
        return result
