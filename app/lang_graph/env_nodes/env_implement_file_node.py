import functools
from pathlib import Path

from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.states.env_implement_state import EnvImplementState, save_env_implement_states_to_json
from app.tools import file_operation
from app.utils.lang_graph_util import get_last_message_content
from app.utils.logger_manager import get_thread_logger


class EnvImplementFileNode:
    SYS_PROMPT = """\
    You are a bash script file manager. Your task is to save the provided bash script in the project. You should:

    1. Examine the project structure to identify the best location for the bash script (typically at the project root)
    2. Use the create_file tool to save the bash script in a SINGLE new file named "prometheus_setup.sh" (with .sh extension, prefix with "prometheus" is needed)
    3. After creating the file, return its relative path

    Tools available:
    - read_file: Read the content of a file
    - create_file: Create a new SINGLE file with specified content


    If the target file already exists and its name starts with "prometheus", overwrite the original file. 
    If the file already exists but its name does not start with "prometheus", create a new file by appending "_2" to the filename. 
    Respond with the relative path of the file that was created or overwritten.
    """

    HUMAN_PROMPT = """\
    Save this bash script in the project:
    {env_implement_bash_content}

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
                env_implement_bash_content=get_last_message_content(
                    state["env_implement_write_messages"]
                ),
                project_structure=self.kg.get_file_tree(),
            )
        )

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
        file_path = ""
        for tool_call in response.tool_calls:
            if tool_call["name"] == file_operation.create_file.__name__:
                file_path = tool_call["args"]["relative_path"]
                break

        # If we found a file path, add it to the state
        if file_path:
            # Convert relative path to Path object for dockerfile_path
            result["env_implement_bash_path"] = Path(file_path)
            self._logger.info(f"Extracted bash script path: {file_path}")
        else:
            self._logger.debug("No file path found in current messages")

        save_env_implement_states_to_json(result, self.local_path)
        return result
