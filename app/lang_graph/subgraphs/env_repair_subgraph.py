import functools
from typing import Mapping, Optional, Sequence, Dict

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

from app.lang_graph.states.env_implement_state import EnvImplementState
from app.lang_graph.repair_nodes.env_repair_execute_node import EnvRepairExecuteNode
from app.lang_graph.repair_nodes.env_repair_analyse_node import EnvRepairAnalyseNode
from app.lang_graph.repair_nodes.env_repair_check_node import EnvRepairCheckNode
from app.lang_graph.repair_nodes.env_repair_update_command_node import EnvRepairUpdateCommandNode

from app.lang_graph.repair_nodes.env_repair_test_execute_node import EnvRepairTestExecuteNode
from app.lang_graph.repair_nodes.env_repair_test_analyse_node import EnvRepairTestAnalyseNode
from app.lang_graph.repair_nodes.env_repair_test_update_command_node import EnvRepairTestUpdateCommandNode


def router_function(state: Dict) -> str:
    """路由器函数：根据输入状态决定流程"""
    env_implement_result = state.get("env_implement_result", {})
    test_result = state.get("test_result", [])

    # 情况1：没有 env_implement_result，首次执行环境命令
    if len(env_implement_result) == 0:
        return "case1"
    
    # 情况2：环境命令失败，需要分析错误（当前env_implement_result为dict，已经是最后一个结果）
    if len(env_implement_result) > 0:
        if isinstance(env_implement_result, dict) and env_implement_result.get('returncode', 0) != 0:
            return "case2"
    
    # 情况3：环境命令成功，但还没有运行测试
    if len(test_result) == 0:
        return "case3"
    
    # 情况4：测试失败，需要分析测试错误（检查最后一个结果）
    if len(test_result) > 0:
        if isinstance(test_result, dict) and test_result.get('returncode', 0) != 0:
            return "case4"
    
    # 默认情况：都成功
    return "success"


def check_router_function(state: Dict) -> str:
    """检查路由器：决定是继续循环还是结束"""
    should_continue = state.get("should_continue", False)
    env_success = state.get("env_success", False)
    test_success = state.get("test_success", False)
    
    # 如果环境成功且测试成功，直接结束
    if env_success and test_success:
        return "end"
    
    # 否则继续循环
    return "continue"

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
        self.base_model = base_model
        self.container = container
        
        # 创建节点
        env_repair_check_node = EnvRepairCheckNode() # 检查状态

        env_repair_execute_node = EnvRepairExecuteNode(container)
        env_repair_analyse_node = EnvRepairAnalyseNode(advanced_model, container)
        env_repair_update_command_node = EnvRepairUpdateCommandNode(advanced_model, container, container.project_path)
        env_repair_update_command_tool_node = ToolNode(
            tools=env_repair_update_command_node.tools,
            name="env_repair_update_command_tool_node",
            messages_key="env_implement_command_messages",
        )
        env_repair_test_execute_node = EnvRepairTestExecuteNode(container)
        env_repair_test_analyse_node = EnvRepairTestAnalyseNode(advanced_model, container)
        env_repair_test_update_command_node = EnvRepairTestUpdateCommandNode(advanced_model, container, container.project_path)
        # 构建工作流
        workflow = StateGraph(EnvImplementState)
        
        # 添加节点
        workflow.add_node("router", lambda state: state)  # 路由器节点
        workflow.add_node("execute_env", env_repair_execute_node)  # 执行环境命令
        workflow.add_node("analyse_env_error_analyse", env_repair_analyse_node)  # 分析环境错误并生成修复命令
        # workflow.add_node("analyse_env_error_analyse_tools", env_repair_analyse_tool_node)  # 读取文件工具
        workflow.add_node("update_command", env_repair_update_command_node)  # 更新命令
        workflow.add_node("update_command_tool", env_repair_update_command_tool_node)  # 更新命令工具
        workflow.add_node("execute_test", env_repair_test_execute_node)  # 执行测试
        workflow.add_node("analyse_test_error", env_repair_test_analyse_node)  # 分析测试错误
        workflow.add_node("update_test_command", env_repair_test_update_command_node)  # 更新测试命令
        workflow.add_node("check_status", env_repair_check_node)  # 检查状态

        # 设置入口点
        workflow.set_entry_point("router")
        
        # 主路由：根据当前状态决定下一步
        workflow.add_conditional_edges(
            "router",
            router_function,
            {
                "case1": "execute_env",
                "case2": "analyse_env_error_analyse",
                "case3": "execute_test",
                "case4": "analyse_test_error",
                "success": END,
            },
        )
        
        # 执行环境命令后，检查状态
        workflow.add_edge("execute_env", "check_status")
        workflow.add_edge("analyse_env_error_analyse", "update_command")
        workflow.add_edge("update_command", "update_command_tool")
        workflow.add_conditional_edges(
            "update_command_tool",
            functools.partial(tools_condition, messages_key="env_implement_command_messages"),
            {
                "tools": "update_command",
                END: "execute_env",
            },
        )
        # Tool execution returns to update_command for continuation
        
        # 执行测试后，检查状态
        workflow.add_edge("execute_test", "check_status")
        workflow.add_edge("analyse_test_error", "update_test_command")
        workflow.add_edge("update_test_command", "execute_test")
        
        
        # 检查状态后，决定是否继续循环
        workflow.add_conditional_edges(
            "check_status",
            check_router_function,
            {
                "continue": "router",  # 继续循环
                "end": END,  # 结束
            },
        )

        # 编译子图
        self.subgraph = workflow.compile()

    def invoke(
        self,
        input_state: Dict,
        recursion_limit: int = 200,
    ):
        config = {"recursion_limit": recursion_limit}
        output_state = self.subgraph.invoke(input_state, config)
        return output_state