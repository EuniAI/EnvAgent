import functools
from typing import Optional, Sequence

import neo4j
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.container.base_container import BaseContainer
from app.git_manage.git_repository import GitRepository
from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.env_nodes.env_implement_file_context_message_node import (
    EnvImplementFileContextMessageNode,
)
from app.lang_graph.env_nodes.env_implement_file_node import EnvImplementFileNode
from app.lang_graph.env_nodes.env_implement_write_message_node import EnvImplementWriteMessageNode
from app.lang_graph.env_nodes.env_implement_write_node import EnvImplementWriteNode
from app.lang_graph.env_nodes.file_context_retrieval_subgraph_node import (
    FileContextRetrievalSubgraphNode,
)
from app.lang_graph.nodes.git_diff_node import GitDiffNode
from app.lang_graph.states.env_implement_state import EnvImplementState, save_env_implement_states_to_json


class EnvImplementSubgraph:
    def __init__(
        self,
        debug_mode: bool,
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
        self.container = container
        env_implement_file_context_message_node = EnvImplementFileContextMessageNode(debug_mode)
        file_context_retrieval_subgraph_node = FileContextRetrievalSubgraphNode(
            base_model,
            kg,
            # git_repo.playground_path,
            container.project_path,
            neo4j_driver,
            max_token_per_neo4j_result,
            query_key_name="env_implement_file_context_query",
            context_key_name="env_implement_file_context",
        )
        env_implement_write_message_node = EnvImplementWriteMessageNode(container.project_path)
        env_implement_write_node = EnvImplementWriteNode(advanced_model, container.project_path)
        env_implement_write_tools = ToolNode(
            tools=env_implement_write_node.tools,
            name="env_implement_write_tools",
            messages_key="env_implement_write_messages",
        )

        # Step 4: Edit files if necessary (based on tool calls)
        env_implement_file_node = EnvImplementFileNode(base_model, kg, container.project_path)
        env_implement_file_tools = ToolNode(
            tools=env_implement_file_node.tools,
            name="env_implement_file_tools",
            messages_key="env_implement_file_messages",
        )
        git_diff_node = GitDiffNode(
            git_repo, "env_implement_bash_content"
        )  # todo: state from env_implement_state

        workflow = StateGraph(EnvImplementState)
        workflow.add_node(
            "env_implement_file_context_message_node", env_implement_file_context_message_node
        )
        if not debug_mode:
            workflow.add_node(
                "file_context_retrieval_subgraph_node", file_context_retrieval_subgraph_node
            )
        workflow.add_node(
            "env_implement_write_message_node", env_implement_write_message_node
        )  # 整合上下文信息，传输指令
        workflow.add_node("env_implement_write_node", env_implement_write_node)  # 写dockerfile
        workflow.add_node("env_implement_write_tools", env_implement_write_tools)
        workflow.add_node("env_implement_file_node", env_implement_file_node)  # 保存dockerfile
        workflow.add_node("env_implement_file_tools", env_implement_file_tools)
        workflow.add_node("git_diff_node", git_diff_node)

        
        workflow.set_entry_point("env_implement_file_context_message_node")
        workflow.add_edge(
            "env_implement_file_context_message_node", "file_context_retrieval_subgraph_node"
        )
        workflow.add_edge(
            "file_context_retrieval_subgraph_node", "env_implement_write_message_node"
        )

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

        config = {"recursion_limit": recursion_limit}
        output_state = self.subgraph.invoke(input_state, config)
        save_env_implement_states_to_json(output_state, self.container.project_path)
        return output_state
