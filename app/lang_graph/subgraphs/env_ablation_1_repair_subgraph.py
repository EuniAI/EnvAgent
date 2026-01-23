import functools
from typing import Dict

import neo4j
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.container.base_container import BaseContainer
from app.git_manage.git_repository import GitRepository
from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.repair_nodes.env_repair_analyse_node import EnvRepairAnalyseNode
from app.lang_graph.repair_nodes.env_repair_check_node import EnvRepairCheckNode, router_function
from app.lang_graph.repair_nodes.env_repair_execute_node import EnvRepairExecuteNode
from app.lang_graph.repair_nodes.env_repair_gen_global_bashfile_node import EnvRepairGenGlobalBashfileNode
from app.lang_graph.repair_nodes.env_repair_test_adjust_node import EnvRepairTestCommandAdjustNode
# from app.lang_graph.repair_nodes.env_repair_test_analyse_node import EnvRepairTestAnalyseNode
from app.lang_graph.repair_nodes.env_repair_test_select_command_node import EnvRepairTestSelectCommandNode
from app.lang_graph.repair_nodes.env_repair_test_execute_node import EnvRepairTestExecuteNode
# from app.lang_graph.repair_nodes.env_repair_test_update_command_node import EnvRepairTestUpdateCommandNode
from app.lang_graph.repair_nodes.env_repair_pyright_execute_node import EnvRepairPyrightExecuteNode
from app.lang_graph.repair_nodes.env_repair_pyright_analyse_node import EnvRepairPyrightAnalyseNode
from app.lang_graph.repair_nodes.env_repair_pytest_execute_node import EnvRepairPytestExecuteNode
from app.lang_graph.repair_nodes.env_repair_pytest_analyse_node import EnvRepairPytestAnalyseNode
from app.lang_graph.repair_nodes.env_repair_update_command_node import EnvRepairUpdateCommandNode
from app.lang_graph.states.env_implement_state import EnvImplementState
from app.utils.logger_manager import get_thread_logger

logger, _file_handler = get_thread_logger(__name__)




def check_router_function(state: Dict) -> str:
    """检查路由器：决定是继续循环还是结束"""
    check_state = state.get("check_state", {})
    
    # 从 check_state 中获取值
    env_success = check_state.get("env_success", False)
    test_success = check_state.get("test_success", False)

    # 如果环境成功且测试成功，直接结束
    if env_success and test_success:
        return "end"
    # 否则继续循环
    return "continue"


class EnvAblation1RepairSubgraph:
    def __init__(
        self,
        debug_mode: bool,
        test_mode: str,
        repair_only_run_env_execute: bool,
        repair_only_run_test_execute: bool,
        advanced_model: BaseChatModel,
        base_model: BaseChatModel,
        container: BaseContainer,
        kg: KnowledgeGraph,
        git_repo: GitRepository,
        neo4j_driver: neo4j.Driver,
    ):
        self.debug_mode = debug_mode
        self.repair_only_run_env_execute = repair_only_run_env_execute
        self.advanced_model = advanced_model
        self.base_model = base_model
        self.container = container
        self.test_mode = test_mode

        # 创建动态路由映射，根据 test_mode 决定 case3 和 case4 的目标
        def create_router_mapping():
                base_mapping = {
                    "case1": "execute_env",
                    "case2": "gen_global_bashfile",  # 使用新节点：只分析错误并生成完整bashfile
                    "success": END,
                }
                # case3 根据 test_mode 决定路由目标
                if repair_only_run_env_execute:
                    base_mapping["case3"] = END # debug 模式下，case3(环境成功，但还没有运行测试)直接成功
                    return base_mapping

                # if test_mode == "pyright":
                #     base_mapping["case3"] = "execute_pyright"
                #     base_mapping["case4"] = "analyse_pyright_error"  # pyright 模式下，case4（检查失败）应该分析pyright错误
                # elif test_mode == "pytest":
                #     base_mapping["case3"] = "execute_pytest"
                #     base_mapping["case4"] = "analyse_pytest_error" # pytest 模式下，case4（测试失败）应该分析测试错误
                if test_mode == "generation":  # generation 模式下，case3（环境成功，但还没有运行测试）应该执行测试
                    base_mapping["case3"] = "test_select_command"
                    base_mapping["case4"] = "gen_global_bashfile" # generation 模式下，case4（测试失败）直接生成全局bashfile（已包含测试错误分析）
                
                return base_mapping

        # 创建节点
        env_repair_check_node = EnvRepairCheckNode(test_mode)  # 检查状态

        env_repair_execute_node = EnvRepairExecuteNode(container)
        # 这里需要只做分析，然后直接生成全局的bashfile，不做单命令生成和update
        env_repair_gen_global_bashfile_node = EnvRepairGenGlobalBashfileNode(advanced_model, container)
        env_repair_analyse_node = EnvRepairAnalyseNode(advanced_model, container)
        # env_repair_update_command_node = EnvRepairUpdateCommandNode(
        #     advanced_model, container, container.project_path
        # )
        # env_repair_update_command_tool_node = ToolNode(
        #     tools=env_repair_update_command_node.tools,
        #     name="env_repair_update_command_tool_node",
        #     messages_key="env_implement_command_messages",
        # )



        # env_repair_test_command_adjust_node = EnvRepairTestCommandAdjustNode(advanced_model, container)
        # env_repair_test_command_adjust_web_search_tool_node = ToolNode(
        #     tools=env_repair_test_command_adjust_node.tools,
        #     name="env_repair_test_command_adjust_web_search_tool_node",
        #     messages_key="test_command_adjust_messages",
        # )
        env_repair_test_select_command_node = EnvRepairTestSelectCommandNode(advanced_model, container)
        env_repair_test_execute_node = EnvRepairTestExecuteNode(container, test_mode)
        # env_repair_test_analyse_node = EnvRepairTestAnalyseNode(advanced_model, container)  # Replaced by env_repair_gen_global_bashfile_node


        
        workflow = StateGraph(EnvImplementState)

        # 添加节点
        workflow.add_node("router", lambda state: state)  # 路由器节点
        workflow.add_node("execute_env", env_repair_execute_node)  # 执行环境命令
        workflow.add_node("gen_global_bashfile", env_repair_gen_global_bashfile_node)  # 分析错误并生成完整bashfile
        # workflow.add_node("analyse_env_error_analyse", env_repair_analyse_node)  # 分析环境错误并生成修复命令（保留用于其他场景）
        # workflow.add_node("update_command", env_repair_update_command_node)  # 更新命令
        # workflow.add_node(
        #     "update_command_tool", env_repair_update_command_tool_node
        # )  # 更新命令工具

        workflow.add_node("check_status", env_repair_check_node)  # 检查状态

        # 根据 test_mode 条件性添加节点
        # if test_mode == "pyright":
        #     workflow.add_node("execute_pyright", env_repair_pyright_execute_node)  # 执行pyright
        #     workflow.add_node("analyse_pyright_error", env_repair_pyright_analyse_node)  # 分析pyright错误
        #     # workflow.add_node(
        #     #     "update_command", env_repair_update_command_node
        #     # )  # 更新测试命令
        # elif test_mode == "pytest":
        #     workflow.add_node("execute_pytest", env_repair_pytest_execute_node)  # 执行pytest
        #     workflow.add_node("analyse_pytest_error", env_repair_pytest_analyse_node)  # 分析pytest错误
        # else:  # generation 模式下，case3（环境成功，但还没有运行测试）应该执行测试
        #     # workflow.add_node("test_command_adjust_web_search_tool", env_repair_test_command_adjust_web_search_tool_node)  # 调整测试命令
        # workflow.add_node("test_command_adjust_node", env_repair_test_command_adjust_node)  # 调整测试命令
        workflow.add_node("test_select_command", env_repair_test_select_command_node)  # 选择测试命令
        workflow.add_node("execute_test", env_repair_test_execute_node)  # 执行测试
        # workflow.add_node("analyse_test_error", env_repair_test_analyse_node)  # 分析测试错误 - Replaced by gen_global_bashfile
            # workflow.add_node(
            #     "update_test_command", env_repair_test_update_command_node
            # )  # 更新测试命令



        # 设置入口点
        # 对test 根据 hierarchy 进行进一步分类、过滤和补充
        if test_mode == "generation":
            # workflow.set_entry_point("test_command_adjust_node")
            workflow.set_entry_point("check_status")
        # workflow.add_conditional_edges(
        #     "test_command_adjust_node",
        #     functools.partial(tools_condition, messages_key="test_command_adjust_messages"),
        #     {
        #         "tools": "test_command_adjust_web_search_tool",
        #         END: "check_status",
        #     },
        # )
        # workflow.add_edge("test_command_adjust_web_search_tool", "test_command_adjust_node")
            # workflow.add_edge("test_command_adjust_node", "check_status")
            workflow.add_edge("check_status", "router")
        # elif test_mode == "pytest" or test_mode == "pyright":
        #     workflow.set_entry_point("check_status")
        #     workflow.add_edge("check_status", "router")

        # 主路由：根据当前状态决定下一步
        workflow.add_conditional_edges(
            "router",
            functools.partial(router_function, test_mode=test_mode),
            create_router_mapping(),
        )

        # 执行环境命令后，检查状态
        workflow.add_edge("execute_env", "check_status")
        # 新节点：生成完整bashfile后直接执行
        workflow.add_edge("gen_global_bashfile", "execute_env")
        # 保留原有流程用于其他场景
        # workflow.add_edge("analyse_env_error_analyse", "gen_global_bashfile")
        # workflow.add_edge("update_command", "update_command_tool")
        # workflow.add_conditional_edges(
        #     "update_command",
        #     functools.partial(tools_condition, messages_key="env_implement_command_messages"),
        #     {
        #         "tools": "update_command_tool",
        #         END: "execute_env",
        #     },
        # )
        # workflow.add_edge("update_command_tool", "update_command")
        # Tool execution returns to update_command for continuation
    
        # 执行测试后，检查状态
        
        # if test_mode == "pyright":
        #     # pyright 模式：执行环境质量检查后，直接检查状态
        #     workflow.add_edge("execute_pyright", "check_status")
        #     # 如果 pyright 检查失败（issues_count > 0），会通过 router 分析错误并生成修复命令
        #     workflow.add_edge("analyse_pyright_error", "update_command")
        #     # workflow.add_edge("update_command", "execute_env")
        #     # 注意：update_command 到 execute_env 的路由由条件边处理（第186-193行），不需要额外的直接边
        # elif test_mode == "pytest":
        #     workflow.add_edge("execute_pytest", "check_status")
        #     workflow.add_edge("analyse_pytest_error", "update_command")
        # else:  # generation 模式下，case3（环境成功，但还没有运行测试）应该执行测试
        #     # workflow.add_edge("test_command_adjust_node", "test_select_command")  # 调整测试命令后选择测试命令
        workflow.add_edge("test_select_command", "execute_test")
        workflow.add_edge("execute_test", "check_status")
        # workflow.add_edge("analyse_test_error", "gen_global_bashfile")  # No longer needed - gen_global_bashfile now handles test analysis directly

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
