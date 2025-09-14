import functools
from typing import Mapping, Optional, Sequence

import neo4j
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition


from app.container.base_container import BaseContainer
from app.git_manage.git_repository import GitRepository
from app.graph.knowledge_graph import KnowledgeGraph
from app.models.context import Context
from app.lang_graph.nodes.bug_reproducing_execute_node import BugReproducingExecuteNode
from app.lang_graph.nodes.bug_reproducing_file_node import BugReproducingFileNode
from app.lang_graph.nodes.bug_reproducing_structured_node import BugReproducingStructuredNode
from app.lang_graph.nodes.bug_reproducing_write_message_node import (
    BugReproducingWriteMessageNode,
)
from app.lang_graph.nodes.bug_reproducing_write_node import BugReproducingWriteNode
from app.lang_graph.nodes.bug_reproduction_context_message_node import (
    BugReproductionContextMessageNode,
)
from app.lang_graph.nodes.context_retrieval_subgraph_node import ContextRetrievalSubgraphNode
from app.lang_graph.nodes.git_diff_node import GitDiffNode
from app.lang_graph.nodes.git_reset_node import GitResetNode
from app.lang_graph.nodes.reset_messages_node import ResetMessagesNode
from app.lang_graph.nodes.update_container_node import UpdateContainerNode
from app.lang_graph.states.bug_reproduction_state import BugReproductionState

from app.lang_graph.env_nodes.env_implement_file_context_message_node import EnvImplementFileContextMessageNode
from app.lang_graph.env_nodes.file_context_retrieval_subgraph_node import FileContextRetrievalSubgraphNode
from app.lang_graph.env_nodes.env_implement_write_message_node import EnvImplementWriteMessageNode
from app.lang_graph.env_nodes.env_implement_write_node import EnvImplementWriteNode
from app.lang_graph.env_nodes.env_implement_file_node import EnvImplementFileNode
from app.lang_graph.states.env_implement_state import EnvImplementState


class EnvImplementSubgraph:
    def __init__(
        self,
        advanced_model: BaseChatModel,
        base_model: BaseChatModel,
        container: BaseContainer,
        kg: KnowledgeGraph,
        git_repo: GitRepository,
        neo4j_driver: neo4j.Driver,
        max_token_per_neo4j_result: int,
        test_commands: Optional[Sequence[str]] = None,
    ):

        self.advanced_model = advanced_model
        env_implement_file_context_message_node = EnvImplementFileContextMessageNode()
        file_context_retrieval_subgraph_node = FileContextRetrievalSubgraphNode(
            base_model,
            kg,
            git_repo.playground_path,
            neo4j_driver,
            max_token_per_neo4j_result,
            query_key_name = "env_implement_file_context_query",    
            context_key_name = "env_implement_file_context",
        )
        env_implement_write_message_node = EnvImplementWriteMessageNode()
        env_implement_write_node = EnvImplementWriteNode(
            advanced_model, git_repo.playground_path
        )
        env_implement_write_tools = ToolNode(
            tools=env_implement_write_node.tools,
            name="env_implement_write_tools",
            messages_key="env_implement_write_messages",
        )

        # Step 4: Edit files if necessary (based on tool calls)
        env_implement_file_node = EnvImplementFileNode(base_model, kg, git_repo.playground_path)
        env_implement_file_tools = ToolNode(
            tools=env_implement_file_node.tools,
            name="env_implement_file_tools",
            messages_key="env_implement_file_messages",
        )
        git_diff_node = GitDiffNode(git_repo, "dockerfile_patch")  # todo: state from env_implement_state


        workflow = StateGraph(EnvImplementState)
        workflow.add_node("env_implement_file_context_message_node", env_implement_file_context_message_node)
        # -----------------test---------------------
        # workflow.add_node("file_context_retrieval_subgraph_node", file_context_retrieval_subgraph_node)
        # -----------------test---------------------
        workflow.add_node("env_implement_write_message_node", env_implement_write_message_node) # 整合上下文信息，传输指令
        workflow.add_node("env_implement_write_node", env_implement_write_node) # 写dockerfile
        workflow.add_node("env_implement_write_tools", env_implement_write_tools)
        workflow.add_node("env_implement_file_node", env_implement_file_node) # 保存dockerfile
        workflow.add_node("env_implement_file_tools", env_implement_file_tools)
        workflow.add_node("git_diff_node", git_diff_node)
        # -----------------test---------------------
        workflow.set_entry_point("env_implement_file_context_message_node")
        # workflow.add_edge("env_implement_file_context_message_node", "file_context_retrieval_subgraph_node")
        # workflow.add_edge("file_context_retrieval_subgraph_node", "env_implement_write_message_node")
        workflow.add_edge("env_implement_file_context_message_node", "env_implement_write_message_node")
        # -----------------test---------------------
        workflow.add_edge("env_implement_write_message_node", "env_implement_write_node")
        # Handle patch-writing tool usage or fallback
        workflow.add_conditional_edges(
            "env_implement_write_node",
            functools.partial(tools_condition, messages_key="env_implement_write_messages"),
            {
                "tools": "env_implement_write_tools",
                END: "env_implement_file_node",
            },
        )
        workflow.add_edge("env_implement_write_tools", "env_implement_write_node")
        
        # Handle file-editing tool usage or fallback
        workflow.add_conditional_edges(
            "env_implement_file_node",
            functools.partial(tools_condition, messages_key="env_implement_file_messages"),
            {
                "tools": "env_implement_file_tools",
                END: "git_diff_node",
            },
        )
        workflow.add_edge("env_implement_file_tools", "env_implement_file_node")


        # Compile the full LangGraph subgraph
        self.subgraph = workflow.compile()

    def invoke(
        self,
        recursion_limit: int = 200,
    ):
        input_state = {
            "max_refined_query_loop": 3,
        }
        
        output_state = self.subgraph.invoke(input_state)
        return output_state
