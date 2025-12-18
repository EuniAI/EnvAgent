
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages
from app.lang_graph.states.testsuite_state import TestsuiteState, save_testsuite_states_to_json
from app.utils.logger_manager import get_thread_logger
from tqdm import tqdm

SYS_PROMPT = """
You are a command extractor. Your goal is to extract ALL runnable shell commands found in the documentation.

Requirements:
- Extract ALL suitable commands found in the documentation
- Include commands that start the software, run tests, check versions, etc.
- Do not skip any commands - extract everything you find
- Do not invent commands; only use commands explicitly shown in the documentation
- Return a simple list of commands without classification
- Remove duplicates
"""

HUMAN_MESSAGE = """
Original user intent:
{original_query}

Documentation snippets observed (may contain irrelevant parts):
{context}

Relative path of the Documentation:
{relative_path}

Task: Extract all runnable shell commands from the documentation. Return them as a list without classification.
"""


class TestsuiteCommandStructuredOutput(BaseModel):
    commands: list[str] = Field(
        description="A list of runnable shell commands extracted from the documentation. Empty list if none found."
    )
    reasoning: str = Field(
        description="Brief justification for the extracted commands."
    )


class TestsuiteContextExtractionNode:
    def __init__(self, model: BaseChatModel, local_path: str):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(TestsuiteCommandStructuredOutput)
        self.model = prompt | structured_llm
        self.local_path = local_path
        self._logger, file_handler = get_thread_logger(__name__)

    def extract_files_from_messages(self, messages: list) -> list[str]:
        """Extract files that were searched from tool messages."""
        involved_files = []
        tool_call_map = {}  # tool_call_id -> (tool_name, args)
        
        # First pass: collect all tool calls from AIMessages
        for message in messages:
            if isinstance(message, AIMessage) and message.tool_calls:
                for tool_call in message.tool_calls:
                    tool_call_id = tool_call.get("id", "")
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    if tool_call_id and tool_name:
                        tool_call_map[tool_call_id] = (tool_name, tool_args)
        
        # Second pass: extract file paths from tool messages
        for message in messages:
            if isinstance(message, ToolMessage):
                tool_call_id = message.tool_call_id
                artifact = getattr(message, "artifact", [])
                
                if tool_call_id in tool_call_map:
                    tool_name, tool_args = tool_call_map[tool_call_id]
                    
                    # Track file search and preview tools
                    if tool_name in ["find_file_node_with_basename", "find_file_node_with_relative_path"]:
                        file_name = tool_args.get("basename") or tool_args.get("relative_path")
                        if file_name and file_name not in involved_files:
                            involved_files.append(file_name)
                            self._logger.debug(f"Marked file as involved (search): {file_name}")
                    elif tool_name in ["preview_file_content_with_basename", "preview_file_content_with_relative_path", 
                                      "read_code_with_basename", "read_code_with_relative_path"]:
                        # First try to get file path from tool arguments
                        file_path = tool_args.get("basename") or tool_args.get("relative_path")
                        if file_path and file_path not in involved_files:
                            involved_files.append(file_path)
                            self._logger.debug(f"Marked file as involved (preview/read from args): {file_path}")
                        
                        # Also extract file paths from artifact if available
                        if isinstance(artifact, list):
                            for item in artifact:
                                if isinstance(item, dict) and "FileNode" in item:
                                    artifact_file_path = item["FileNode"].get("relative_path")
                                    if artifact_file_path and artifact_file_path not in involved_files:
                                        involved_files.append(artifact_file_path)
                                        self._logger.debug(f"Marked file as involved (preview/read from artifact): {artifact_file_path}")
        
        return involved_files

    def get_human_messages(self, state: TestsuiteState) -> list[str]:
        """Extract all ToolMessages from testsuite_context_provider_messages and generate human messages."""
        human_messages = []
        all_messages = state.get("testsuite_context_provider_messages", [])
        
        # Get all ToolMessages directly
        tool_messages = [msg for msg in all_messages if isinstance(msg, ToolMessage)]
        self._logger.info(f"Found {len(tool_messages)} ToolMessages in testsuite_context_provider_messages")
        
        original_query = state.get("query", "Find a quick verification command from docs")
        
        # Process all ToolMessages
        for tool_msg in tool_messages:
            artifact = getattr(tool_msg, "artifact", [])
            if not artifact:
                continue
            
            if not isinstance(artifact, list):
                artifact = [artifact]
            
            for context in artifact:
                if not isinstance(context, dict):
                    continue
                
                # Extract preview and relative_path
                preview = context.get("preview") or context.get("content") or context.get("text")
                if not preview:
                    continue
                
                # Extract relative_path
                if "FileNode" in context and isinstance(context["FileNode"], dict):
                    relative_path = context["FileNode"].get("relative_path", "documentation")
                else:
                    relative_path = context.get("relative_path") or context.get("file_path") or "documentation"
                
                human_messages.append(
                    HUMAN_MESSAGE.format(
                        original_query=original_query,
                        context=preview,
                        relative_path=relative_path,
                    )
                )
        
        self._logger.info(f"Generated {len(human_messages)} human messages for command extraction")
        return human_messages

    def __call__(self, state: TestsuiteState):
        """
        Extract a single verification command from documentation snippets gathered by the provider tools.
        """
        self._logger.info("Starting testsuite command extraction process")
        existing_command = state.get("testsuite_command", "")
        if existing_command:
            self._logger.info("Command already present in state; skipping extraction")
            # Clear messages even when skipping extraction to keep only current round info
            # Directly clear the list since add_messages will append, not replace
            if "testsuite_context_provider_messages" in state and isinstance(state["testsuite_context_provider_messages"], list):
                state["testsuite_context_provider_messages"].clear()
            return {
                "testsuite_command": existing_command,
            }
        human_messages = self.get_human_messages(state)
        
        if not human_messages:
            self._logger.warning("No human messages generated from testsuite_context_provider_messages")
            # Update involved_files even if no messages
            previous_messages = state.get("testsuite_context_provider_messages", [])
            involved_files_from_messages = self.extract_files_from_messages(previous_messages)
            existing_involved_files = state.get("involved_files", [])
            if not isinstance(existing_involved_files, list):
                existing_involved_files = list(existing_involved_files) if existing_involved_files else []
            all_involved_files = list(existing_involved_files)
            for file_name in involved_files_from_messages:
                if file_name not in all_involved_files:
                    all_involved_files.append(file_name)
            
            if "testsuite_context_provider_messages" in state and isinstance(state["testsuite_context_provider_messages"], list):
                state["testsuite_context_provider_messages"].clear()
            state_update = {
                "testsuite_command": [],
                "involved_files": all_involved_files,
            }
            state_for_saving = dict(state)
            state_for_saving["testsuite_command"] = []
            state_for_saving["involved_files"] = all_involved_files
            state_for_saving["testsuite_context_provider_messages"] = []
            save_testsuite_states_to_json(state_for_saving, self.local_path)
            return state_update
        
        # Extract commands from all human messages
        all_commands = []
        for human_message in tqdm(human_messages, desc="Extracting commands"):
            try:
                response = self.model.invoke({"human_prompt": human_message})
                self._logger.debug(f"Response: {response}")
                commands = response.commands or []
                for command in commands:
                    command = command.strip()
                    if command:
                        all_commands.append(command)
            except Exception as e:
                self._logger.error(f"Error extracting commands: {e}", exc_info=True)
        
        # Remove duplicates while preserving order
        commands = list(dict.fromkeys(all_commands))
        self._logger.info(f"Extracted {len(commands)} unique commands: {commands}")

        ############# 保存involved file #############
        # Extract files that were searched from tool messages
        previous_messages = state.get("testsuite_contex_provider_messages", [])
        involved_files_from_messages = self.extract_files_from_messages(previous_messages)
        # Merge with existing involved_files in state (avoid duplicates)
        existing_involved_files = state.get("involved_files", [])
        if not isinstance(existing_involved_files, list):
            existing_involved_files = list(existing_involved_files) if existing_involved_files else []
        all_involved_files = list(existing_involved_files)
        for file_name in involved_files_from_messages:
            if file_name not in all_involved_files:
                all_involved_files.append(file_name)
        
        if involved_files_from_messages:
            self._logger.info(f"Found {len(involved_files_from_messages)} newly involved files: {involved_files_from_messages}")
        
        if commands:

            ############# 保存involved command #############
            self._logger.info(f"Extracted verification commands: {commands}")
            # Update involved_commands to track all searched commands
            existing_involved_commands = state.get("involved_commands", [])
            if not isinstance(existing_involved_commands, list):
                existing_involved_commands = list(existing_involved_commands) if existing_involved_commands else []
            # Add new commands to involved_commands, avoiding duplicates
            updated_involved_commands = list(dict.fromkeys(existing_involved_commands + commands))
            # Directly clear the list since add_messages will append, not replace
            if "testsuite_context_provider_messages" in state and isinstance(state["testsuite_context_provider_messages"], list):
                state["testsuite_context_provider_messages"].clear()
            state_update = {
                "testsuite_command": commands,
                "involved_commands": updated_involved_commands,
                "involved_files": all_involved_files,
            }

            ############# 保存state json文件 #############
            state_for_saving = dict(state)
            state_for_saving["testsuite_command"] = add_messages(
                state.get("testsuite_command", []),
                commands
            )
            state_for_saving["involved_commands"] = updated_involved_commands
            state_for_saving["involved_files"] = all_involved_files
            state_for_saving["testsuite_context_provider_messages"] = []  # Clear messages in saved state
            save_testsuite_states_to_json(state_for_saving, self.local_path)
            self._logger.info("Cleared testsuite_context_provider_messages after extraction, history saved in involved_files and involved_commands")
            return state_update
        else:
            self._logger.info("No suitable commands found in current snippets")
            # Even if no commands found, update involved_files
            # Directly clear the list since add_messages will append, not replace
            if "testsuite_context_provider_messages" in state and isinstance(state["testsuite_context_provider_messages"], list):
                state["testsuite_context_provider_messages"].clear()
            state_update = {
                "testsuite_command": [],
                "involved_files": all_involved_files,
            }
            state_for_saving = dict(state)
            state_for_saving["testsuite_command"] = []
            state_for_saving["involved_files"] = all_involved_files
            state_for_saving["testsuite_context_provider_messages"] = []  # Clear messages in saved state
            save_testsuite_states_to_json(state_for_saving, self.local_path)
            self._logger.info("Cleared testsuite_context_provider_messages after extraction, history saved in involved_files and involved_commands")
            return state_update
