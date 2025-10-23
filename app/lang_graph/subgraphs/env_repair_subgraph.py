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

from app.lang_graph.repair_nodes.env_repair_context_message_node import EnvRepairContextMessageNode
from app.lang_graph.repair_nodes.env_repair_write_node import EnvRepairWriteNode
# from app.lang_graph.repair_nodes.file_context_retrieval_subgraph_node import FileContextRetrievalSubgraphNode
# from app.lang_graph.repair_nodes.env_implement_write_message_node import EnvImplementWriteMessageNode
# from app.lang_graph.repair_nodes.env_implement_write_node import EnvImplementWriteNode
from app.lang_graph.repair_nodes.env_implement_file_node import EnvImplementFileNode
from app.lang_graph.states.env_implement_state import EnvImplementState


class EnvRepairSubgraph:
    def __init__(
        self,
        debug_mode: bool,
        advanced_model: BaseChatModel,
        base_model: BaseChatModel,
        container: BaseContainer,
        kg: KnowledgeGraph,
        git_repo: GitRepository,
        neo4j_driver: neo4j.Driver,
    ):
        self.advanced_model = advanced_model
        env_repair_context_message_node = EnvRepairContextMessageNode(debug_mode)
        env_repair_write_node = EnvRepairWriteNode(base_model, kg, neo4j_driver)
        

        # Step 4: Edit files if necessary (based on tool calls)
        env_implement_file_node = EnvImplementFileNode(base_model, kg, container.project_path)
        env_implement_file_tools = ToolNode(
            tools=env_implement_file_node.tools,
            name="env_implement_file_tools",
            messages_key="env_implement_file_messages",
        )
        git_diff_node = GitDiffNode(git_repo, "env_implement_bash_content")  # todo: state from env_implement_state


        workflow = StateGraph(EnvImplementState)
        workflow.add_node("env_repair_context_message_node", env_repair_context_message_node)
        workflow.add_node("env_repair_write_node", env_repair_write_node)
        workflow.add_node("env_implement_file_node", env_implement_file_node) # 保存dockerfile
        workflow.add_node("env_implement_file_tools", env_implement_file_tools)
        workflow.add_node("git_diff_node", git_diff_node)

        workflow.set_entry_point("env_repair_context_message_node")
        workflow.add_edge("env_repair_context_message_node", "env_repair_write_node")
        workflow.add_edge("env_repair_write_node", "env_implement_file_node")
        
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
        env_implement_command: str,
        env_implement_result: str,
        test_command: str,
        test_result: str,
    ):
        input_state = {
            "env_implement_command": env_implement_command,
            "env_implement_result": env_implement_result,
            "test_command": test_command,
            "test_result": test_result,
        }
        
        output_state = self.subgraph.invoke(input_state)
        return output_state