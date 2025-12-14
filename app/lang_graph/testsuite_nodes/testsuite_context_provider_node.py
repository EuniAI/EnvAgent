"""Knowledge graph-based context provider for codebase queries.

This module implements a specialized context provider that uses a Neo4j knowledge graph
to find relevant code context based on user queries. It leverages a language model
with structured tools to systematically search and analyze the codebase KnowledgeGraph.
"""

import functools
from typing import Dict, List

import neo4j
from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from pathlib import Path
from langgraph.graph.message import add_messages
from app.graph.knowledge_graph import KnowledgeGraph
from app.tools import graph_traversal
from app.utils.logger_manager import get_thread_logger
from app.lang_graph.states.testsuite_state import TestsuiteState, save_testsuite_states_to_json


class TestsuiteContextProviderNode:
    """Provides contextual information from a codebase using knowledge graph search.

    This class implements a systematic approach to finding relevant code context
    by searching through a Neo4j knowledge graph representation of a codebase.
    It uses a combination of file structure navigation, AST analysis, and text
    search to gather comprehensive context for queries.

    The knowledge graph contains three main types of nodes:
    - FileNode: Represents files and directories
    - ASTNode: Represents syntactic elements from the code
    - TextNode: Represents documentation and text content
    """

    SYS_PROMPT = """\
You are a multi-dimensional entry point finder. Core principle: Level 1 is TARGET, Level 3/4 are DIAGNOSTIC tools.

Goal: Search for ALL test/command types from ALL levels (1-4). Extract everything you find.

Command types to search for (find all):
1) Entry Points (Level 1 - TARGET): Commands that start the actual software
   - Python: "python main.py", "python -m package", "uvicorn app:app"
   - Node.js: "npm start", "node server.js", "npm run dev"
   - Rust: "cargo run", "./target/release/app"
   - Go: "go run main.go", "./app"
2) Integration Tests (Level 2): Tests with real dependencies
   - "pytest --integration", "npm run test:e2e", "make integration-test"
3) Smoke Tests (Level 3 - Diagnostic): Quick verification for blocking issues
   - "<tool> --version", "<tool> --help", "make check"
4) Unit Tests (Level 4 - Diagnostic only): For detailed error info, not as repair target
   - "pytest -q", "npm test", "cargo test", "go test"

Target files (search all):
1) README.md - Look for "Usage", "Quick Start", "Running", "Testing" sections
2) docs/quickstart.md, docs/getting-started.md, docs/testing.md
3) package.json, Cargo.toml, go.mod, pom.xml - Look for "scripts" or "bin" entries
4) Makefile - Look for "run", "start", "serve", "test" targets
5) Test files: test/, tests/, __tests__/, *_test.py, *_test.js, etc.

Search strategy:
1. Use find_file_node_with_basename to locate README and test-related files
2. Use preview_file_content_* to scan for ALL command types (Level 1-4)
3. Search comprehensively - find all test commands from all levels
4. Do not stop early - continue searching until you've covered relevant files

The file tree of the codebase:
{file_tree}

Available AST node types (for completeness): {ast_node_types}

REMEMBER: Entry points > Integration > Smoke > Unit tests. Find ONE file, scan quickly, then STOP.
"""

    def __init__(
        self,
        model: BaseChatModel,
        kg: KnowledgeGraph,
        neo4j_driver: neo4j.Driver,
        max_token_per_result: int,
        local_path: Path,
    ):
        """Initializes the ContextProviderNode with model, knowledge graph, and database connection.

        Sets up the context provider with necessary prompts, graph traversal tools,
        and logging configuration. Initializes the system prompt with the current
        file tree structure from the knowledge graph.

        Args:
          model: Language model instance that will be used for query analysis and
            context finding. Must be a BaseChatModel implementation that supports
            tool binding.
          kg: Knowledge graph instance containing the processed codebase structure.
            Used to obtain the file tree for system prompts.
          neo4j_driver: Neo4j driver instance for executing graph queries. This
            driver should be properly configured with authentication and
            connection details.
          max_token_per_result: Maximum number of tokens per retrieved Neo4j result.
        """
        self.neo4j_driver = neo4j_driver
        self.root_node_id = kg.root_node_id
        self.max_token_per_result = max_token_per_result

        ast_node_types_str = ", ".join(kg.get_all_ast_node_types())
        self.system_prompt = SystemMessage(
            self.SYS_PROMPT.format(file_tree=kg.get_file_tree(), ast_node_types=ast_node_types_str)
        )
        self.tools = self._init_tools()
        self.model_with_tools = model.bind_tools(self.tools)
        self._logger, _file_handler = get_thread_logger(__name__)
        self.local_path = local_path
    def _init_tools(self):
        """
        Initializes KnowledgeGraph traversal tools.

        Returns:
          List of StructuredTool instances configured for KnowledgeGraph traversal.
        """
        tools = []

        # === FILE SEARCH TOOLS ===

        # Tool: Find file node by filename (basename)
        # Used when only the filename (not full path) is known
        find_file_node_with_basename_fn = functools.partial(
            graph_traversal.find_file_node_with_basename,
            driver=self.neo4j_driver,
            max_token_per_result=self.max_token_per_result,
            root_node_id=self.root_node_id,
        )
        find_file_node_with_basename_tool = StructuredTool.from_function(
            func=find_file_node_with_basename_fn,
            name=graph_traversal.find_file_node_with_basename.__name__,
            description=graph_traversal.FIND_FILE_NODE_WITH_BASENAME_DESCRIPTION,
            args_schema=graph_traversal.FindFileNodeWithBasenameInput,
            response_format="content_and_artifact",
        )
        tools.append(find_file_node_with_basename_tool)

        # Tool: Find file node by relative path
        # Preferred method when the exact file path is known
        find_file_node_with_relative_path_fn = functools.partial(
            graph_traversal.find_file_node_with_relative_path,
            driver=self.neo4j_driver,
            max_token_per_result=self.max_token_per_result,
            root_node_id=self.root_node_id,
        )
        find_file_node_with_relative_path_tool = StructuredTool.from_function(
            func=find_file_node_with_relative_path_fn,
            name=graph_traversal.find_file_node_with_relative_path.__name__,
            description=graph_traversal.FIND_FILE_NODE_WITH_RELATIVE_PATH_DESCRIPTION,
            args_schema=graph_traversal.FindFileNodeWithRelativePathInput,
            response_format="content_and_artifact",
        )
        tools.append(find_file_node_with_relative_path_tool)
        # === TEXT/DOCUMENT SEARCH TOOLS ===

        # Tool: Find text node globally by keyword
        find_text_node_with_text_fn = functools.partial(
            graph_traversal.find_text_node_with_text,
            driver=self.neo4j_driver,
            max_token_per_result=self.max_token_per_result,
            root_node_id=self.root_node_id,
        )
        find_text_node_with_text_tool = StructuredTool.from_function(
            func=find_text_node_with_text_fn,
            name=graph_traversal.find_text_node_with_text.__name__,
            description=graph_traversal.FIND_TEXT_NODE_WITH_TEXT_DESCRIPTION,
            args_schema=graph_traversal.FindTextNodeWithTextInput,
            response_format="content_and_artifact",
        )
        tools.append(find_text_node_with_text_tool)

        # Tool: Find text node by keyword in specific file
        find_text_node_with_text_in_file_fn = functools.partial(
            graph_traversal.find_text_node_with_text_in_file,
            driver=self.neo4j_driver,
            max_token_per_result=self.max_token_per_result,
            root_node_id=self.root_node_id,
        )
        find_text_node_with_text_in_file_tool = StructuredTool.from_function(
            func=find_text_node_with_text_in_file_fn,
            name=graph_traversal.find_text_node_with_text_in_file.__name__,
            description=graph_traversal.FIND_TEXT_NODE_WITH_TEXT_IN_FILE_DESCRIPTION,
            args_schema=graph_traversal.FindTextNodeWithTextInFileInput,
            response_format="content_and_artifact",
        )
        tools.append(find_text_node_with_text_in_file_tool)

        # Tool: Fetch the next text node chunk in a chain (used for long docs/comments)
        get_next_text_node_with_node_id_fn = functools.partial(
            graph_traversal.get_next_text_node_with_node_id,
            driver=self.neo4j_driver,
            max_token_per_result=self.max_token_per_result,
            root_node_id=self.root_node_id,
        )
        get_next_text_node_with_node_id_tool = StructuredTool.from_function(
            func=get_next_text_node_with_node_id_fn,
            name=graph_traversal.get_next_text_node_with_node_id.__name__,
            description=graph_traversal.GET_NEXT_TEXT_NODE_WITH_NODE_ID_DESCRIPTION,
            args_schema=graph_traversal.GetNextTextNodeWithNodeIdInput,
            response_format="content_and_artifact",
        )
        tools.append(get_next_text_node_with_node_id_tool)

        # === FILE PREVIEW & READING TOOLS ===

        # Tool: Preview contents of file by basename
        preview_file_content_with_basename_fn = functools.partial(
            graph_traversal.preview_file_content_with_basename,
            driver=self.neo4j_driver,
            max_token_per_result=self.max_token_per_result,
            root_node_id=self.root_node_id,
        )
        preview_file_content_with_basename_tool = StructuredTool.from_function(
            func=preview_file_content_with_basename_fn,
            name=graph_traversal.preview_file_content_with_basename.__name__,
            description=graph_traversal.PREVIEW_FILE_CONTENT_WITH_BASENAME_DESCRIPTION,
            args_schema=graph_traversal.PreviewFileContentWithBasenameInput,
            response_format="content_and_artifact",
        )
        tools.append(preview_file_content_with_basename_tool)

        # Tool: Preview contents of file by relative path
        preview_file_content_with_relative_path_fn = functools.partial(
            graph_traversal.preview_file_content_with_relative_path,
            driver=self.neo4j_driver,
            max_token_per_result=self.max_token_per_result,
            root_node_id=self.root_node_id,
        )
        preview_file_content_with_relative_path_tool = StructuredTool.from_function(
            func=preview_file_content_with_relative_path_fn,
            name=graph_traversal.preview_file_content_with_relative_path.__name__,
            description=graph_traversal.PREVIEW_FILE_CONTENT_WITH_RELATIVE_PATH_DESCRIPTION,
            args_schema=graph_traversal.PreviewFileContentWithRelativePathInput,
            response_format="content_and_artifact",
        )
        tools.append(preview_file_content_with_relative_path_tool)

        return tools

    def _truncate_messages(
        self, messages: List[BaseMessage], max_tokens: int = 6000
    ) -> List[BaseMessage]:
        """
        Truncate message history to fit within token limits.

        Args:
            messages: List of messages to truncate
            max_tokens: Maximum number of tokens to keep (default 6000 to leave room for response)

        Returns:
            Truncated list of messages
        """
        if not messages:
            return messages

        # Keep system prompt and recent messages
        truncated_messages = []
        current_tokens = 0

        # Rough token estimation (1 token ≈ 4 characters for English text)
        def estimate_tokens(text: str) -> int:
            return len(text) // 4

        # Always keep the first message (usually system prompt)
        if messages:
            first_msg = messages[0]
            truncated_messages.append(first_msg)
            current_tokens += estimate_tokens(first_msg.content)

        # Add messages from the end (most recent first) until we hit the limit
        for msg in reversed(messages[1:]):
            msg_tokens = estimate_tokens(msg.content)
            if current_tokens + msg_tokens > max_tokens:
                break
            truncated_messages.insert(1, msg)  # Insert after system prompt
            current_tokens += msg_tokens

        self._logger.debug(
            f"Truncated messages from {len(messages)} to {len(truncated_messages)} messages"
        )
        return truncated_messages

    def __call__(self, state: Dict):
        """Processes the current state and traverse the knowledge graph to retrieve context.

        Args:
          state: Current state containing the human query and previous context_messages.

        Returns:
          Dictionary that will update the state with the model's response messages.
        """
        # Check for repeated queries to prevent infinite loops
        messages = state.get("testsuite_context_provider_messages", [])
        if len(messages) > 3:
            # Check if the last 3 messages contain ToolMessage (tool responses)
            from langchain_core.messages import ToolMessage

            recent_tool_messages = [msg for msg in messages if isinstance(msg, ToolMessage)]
            if len(recent_tool_messages) >= 3:
                # If we have multiple recent tool messages, check for repetition
                self._logger.warning(
                    "Detected potential repeated tool calls, stopping to prevent infinite loop"
                )
                return {"testsuite_context_provider_messages": []}

        # self._logger.debug(f"Context provider messages: {state['context_provider_messages']}")
        message_history = [self.system_prompt] + state["testsuite_context_provider_messages"]

        # Truncate messages if they exceed token limits
        truncated_history = self._truncate_messages(message_history)

        try:
            response = self.model_with_tools.invoke(truncated_history)
            self._logger.debug(response)
            # The response will be added to the bottom of the list
            state_update = {"testsuite_context_provider_messages": [response]}
            state_for_saving = dict(state)
            state_for_saving["testsuite_context_provider_messages"] = add_messages(
                state.get("testsuite_context_provider_messages", []),
                [response]
            )
            save_testsuite_states_to_json(state_for_saving, self.local_path)
            return state_update
        except Exception as e:
            if "context_length_exceeded" in str(e):
                self._logger.warning(
                    "Context length exceeded, trying with more aggressive truncation"
                )
                # Try with even more aggressive truncation
                truncated_history = self._truncate_messages(message_history, max_tokens=4000)
                response = self.model_with_tools.invoke(truncated_history)
                self._logger.debug(response)
                state_update = {"testsuite_context_provider_messages": [response]}
                state_for_saving = dict(state)
                state_for_saving["testsuite_context_provider_messages"] = add_messages(
                    state.get("testsuite_context_provider_messages", []),
                    [response]
                )
                save_testsuite_states_to_json(state_for_saving, self.local_path)
                return state_update
            else:
                raise
