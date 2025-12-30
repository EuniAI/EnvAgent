from typing import Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.exceptions.file_operation_exception import FileOperationException
from app.lang_graph.states.context_retrieval_state import ContextRetrievalState
from app.models.context import Context
from app.utils.file_utils import read_file_with_line_numbers
from app.utils.lang_graph_util import (
    extract_last_tool_messages,
    transform_tool_messages_to_str,
)
from app.utils.logger_manager import get_thread_logger
from app.utils.neo4j_util import EMPTY_DATA_MESSAGE
from app.lang_graph.states.env_implement_state import save_env_implement_states_to_json

SYS_PROMPT = """\
You are a context extraction agent for environment configuration files. Your task is to READ COMPLETE FILE CONTENT and extract parts relevant to environment setup for Dockerfile generation.

EXTRACTION PROCESS:
1. Read the COMPLETE file content that you have seen
2. Identify which parts are relevant to environment configuration based on the query and testsuite commands
3. Extract those relevant parts with exact line numbers

TESTSuite COMMANDS GUIDE:
The query includes testsuite commands that need to run successfully. Use these commands to guide your extraction:
- Analyze what dependencies, build tools, and runtime requirements are needed to run these commands
- Extract configuration files that define these requirements
- For Level 1 commands (Entry Points): Focus on files needed to start the software
- For Level 2-4 commands (Tests): Focus on files needed for testing environment

FILE TYPE HANDLING:

CONFIGURATION FILES (Extract COMPLETE content):
- Dependency files: requirements.txt, package.json, go.mod, Cargo.toml, pom.xml, build.gradle
- Build configs: Makefile, CMakeLists.txt, build.xml
- Environment: .env, config.json, docker-compose.yml, Dockerfile
- Documentation: README.md, INSTALL.md, SETUP.md
→ Extract ENTIRE file (start_line=1, end_line=last_line)

CODE FILES (Extract relevant sections):
- Source files (.py, .js, .java, .go, .rs, etc.)
→ Extract only sections related to:
  * Dependencies (imports, requires)
  * Build configuration
  * Entry points
  * Runtime requirements

EXTRACTION RULES:
- Read complete file first, then extract relevant parts
- Configuration files: Extract complete content
- Code files: Extract only environment-related sections
- Match extraction to testsuite command requirements
- Do not duplicate contexts

Return structured output with reasoning, file path, and line numbers.
"""

HUMAN_MESSAGE = """\
This is the original user query (includes testsuite commands):
{original_query}

The complete file content that you have seen:
{context}

TASK:
1. Read the COMPLETE file content above
2. Identify parts relevant to environment configuration based on:
   - The testsuite commands in the query
   - Dependencies, build tools, and runtime requirements needed
3. Extract relevant parts with exact line numbers
4. For configuration files: Extract complete content (all lines)
5. For code files: Extract only environment-related sections

Return the extracted contexts in the specified format.
"""


class ContextOutput(BaseModel):
    reasoning: str = Field(
        description="Your step-by-step reasoning why the context is relevant to the query"
    )
    relative_path: str = Field(description="Relative path to the context file in the codebase")
    start_line: int = Field(
        description="Start line number of the context in the file, minimum is 1"
    )
    end_line: int = Field(
        description="End line number of the context in the file, minimum is 1. "
        "The Content in the end line is including"
    )


class ContextExtractionStructuredOutput(BaseModel):
    context: Sequence[ContextOutput] = Field(
        description="List of contexts extracted from the history messages. "
        "Each context must have a reasoning, relative path, start line and end line."
    )


class EnvImplementFileContextExtractionNode:
    def __init__(self, model: BaseChatModel, root_path: str):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(ContextExtractionStructuredOutput)
        self.model = prompt | structured_llm
        self.root_path = root_path
        self._logger, file_handler = get_thread_logger(__name__)

    def get_human_message(self, state: ContextRetrievalState) -> str:
        full_context_str = transform_tool_messages_to_str(
            extract_last_tool_messages(state["context_provider_messages"])
        )
        original_query = state["query"]
        return HUMAN_MESSAGE.format(
            original_query=original_query,
            context=full_context_str,
        )

    def extract_files_from_messages(self, messages: list) -> list[str]:
        """Extract files that were searched but not found from tool messages."""
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
        
        # Second pass: check ToolMessages for empty results
        for message in messages:
            if isinstance(message, ToolMessage):
                tool_call_id = message.tool_call_id
                content = str(message.content) if message.content else ""
                artifact = getattr(message, "artifact", [])
                
                # Check if empty result: content contains EMPTY_DATA_MESSAGE or artifact is empty list
                is_empty = EMPTY_DATA_MESSAGE in content or (isinstance(artifact, list) and len(artifact) == 0)
                
                if is_empty and tool_call_id in tool_call_map:
                    tool_name, tool_args = tool_call_map[tool_call_id]
                    
                    # Only track file search tools
                    if tool_name in ["find_file_node_with_basename", "find_file_node_with_relative_path"]:
                        file_name = tool_args.get("basename") or tool_args.get("relative_path")
                        if file_name and file_name not in involved_files:
                            involved_files.append(file_name)
                            self._logger.debug(f"Marked file as involved: {file_name}")
        
        return involved_files

    def __call__(self, state: ContextRetrievalState):
        """
        Extract relevant code contexts from the codebase based on the user query and existing context.
        The final contexts are with line numbers.
        Also extracts not found files from tool messages before they are reset.
        """
        self._logger.info("Starting context extraction process")
        # Get Context List with existing context
        final_context = state.get("context", [])
        # Get a human message
        human_message = self.get_human_message(state)
        self._logger.debug(human_message)
        # Summarize the context based on the last messages and system prompt
        response = self.model.invoke({"human_prompt": human_message})
        self._logger.debug(f"Model response: {response}")
        context_list = response.context
        for context_ in context_list:
            if context_.start_line < 1 or context_.end_line < 1:
                self._logger.warning(
                    f"Skipping invalid context with start_line={context_.start_line}, end_line={context_.end_line}"
                )
                continue
            try:
                content = read_file_with_line_numbers(
                    relative_path=context_.relative_path,
                    root_path=str(self.root_path),
                    start_line=context_.start_line,
                    end_line=context_.end_line,
                )
            except FileOperationException as e:
                self._logger.error(e)
                continue
            if not content:
                self._logger.warning(
                    f"Skipping context with empty content for {context_.relative_path} "
                    f"from line {context_.start_line} to {context_.end_line}"
                )
                continue
            context = Context(
                relative_path=context_.relative_path,
                start_line_number=context_.start_line,
                end_line_number=context_.end_line,
                content=content,
            )
            if context not in final_context:
                final_context = final_context + [context]

        # Extract not found files from messages before they are reset
        previous_messages = state.get("context_provider_messages", [])
        involved_files = self.extract_files_from_messages(previous_messages)
        
        # Merge with existing not_found_files in state (avoid duplicates)
        existing_involved_files = state.get("involved_files", [])
        if not isinstance(existing_involved_files, list):
            existing_involved_files = list(existing_involved_files) if existing_involved_files else []
        
        all_involved_files = list(existing_involved_files)
        for file_name in involved_files:
            if file_name not in all_involved_files:
                all_involved_files.append(file_name)
            else:
                self._logger.info(f"File {file_name} already involved, skipping")
        
        
        if involved_files:
            self._logger.info(f"Found {len(involved_files)} newly involved files: {involved_files}")

        # self._logger.info(f"Context extraction complete, returning context {final_context}")
        state_update = {
            "context": final_context,
            "involved_files": all_involved_files,
        }
        # Don't manually update state - let LangGraph handle it
        # Create a copy with updated values for saving
        state_for_saving = dict(state)
        state_for_saving.update(state_update)
        save_env_implement_states_to_json(state_for_saving, self.root_path)
        return state_update
