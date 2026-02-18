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
from app.lang_graph.repair_nodes.env_repair_test_adjust_node import EnvRepairTestCommandAdjustNode
from app.lang_graph.repair_nodes.env_repair_test_analyse_node import EnvRepairTestAnalyseNode
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
    """Check router: decide whether to continue looping or end."""
    check_state = state.get("check_state", {})
    
    # Get values from check_state
    env_success = check_state.get("env_success", False)
    test_success = check_state.get("test_success", False)

    # If environment and tests both succeed, end
    if env_success and test_success:
        return "end"
    # Otherwise, continue looping
    return "continue"


class EnvRepairSubgraph:
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

        # Create a dynamic routing map; use test_mode to decide targets for case3 and case4
        def create_router_mapping():
                base_mapping = {
                    "case1": "execute_env",
                    "case2": "analyse_env_error_analyse",
                    "success": END,
                }
                # case3's routing target depends on test_mode
                if repair_only_run_env_execute:
                    base_mapping["case3"] = END  # In debug mode, case3 (environment succeeded but tests have not yet run) is treated as success
                    return base_mapping

                if test_mode == "pyright":
                    base_mapping["case3"] = "execute_pyright"
                    base_mapping["case4"] = "analyse_pyright_error"  # In pyright mode, case4 (check failed) should analyze pyright errors
                elif test_mode == "pytest":
                    base_mapping["case3"] = "execute_pytest"
                    base_mapping["case4"] = "analyse_pytest_error"  # In pytest mode, case4 (tests failed) should analyze test errors
                elif test_mode == "generation":  # In generation mode, case3 (environment succeeded but tests have not yet run) should execute tests
                    base_mapping["case3"] = "test_select_command"
                    base_mapping["case4"] = "analyse_test_error"  # In generation mode, case4 (tests failed) should analyze test errors
                
                return base_mapping

        # Create nodes
        env_repair_check_node = EnvRepairCheckNode(test_mode)  # Check status

        env_repair_execute_node = EnvRepairExecuteNode(container)
        env_repair_analyse_node = EnvRepairAnalyseNode(advanced_model, container)
        env_repair_update_command_node = EnvRepairUpdateCommandNode(
            advanced_model, container, container.project_path
        )
        env_repair_update_command_tool_node = ToolNode(
            tools=env_repair_update_command_node.tools,
            name="env_repair_update_command_tool_node",
            messages_key="env_implement_command_messages",
        )

        env_repair_test_command_adjust_node = EnvRepairTestCommandAdjustNode(advanced_model, container)
        env_repair_test_command_adjust_web_search_tool_node = ToolNode(
            tools=env_repair_test_command_adjust_node.tools,
            name="env_repair_test_command_adjust_web_search_tool_node",
            messages_key="test_command_adjust_messages",
        )
        env_repair_test_select_command_node = EnvRepairTestSelectCommandNode(advanced_model, container)
        env_repair_test_execute_node = EnvRepairTestExecuteNode(container, test_mode)
        env_repair_test_analyse_node = EnvRepairTestAnalyseNode(advanced_model, container)
        # env_repair_test_update_command_node = EnvRepairTestUpdateCommandNode(advanced_model, container, container.project_path)

        # pyright mode
        env_repair_pyright_execute_node = EnvRepairPyrightExecuteNode(container)
        env_repair_pyright_analyse_node = EnvRepairPyrightAnalyseNode(advanced_model, container)


        env_repair_pytest_execute_node = EnvRepairPytestExecuteNode(container)
        env_repair_pytest_analyse_node = EnvRepairPytestAnalyseNode(advanced_model, container)



        if not repair_only_run_env_execute:  # Debug environment bashfile and tests
            workflow = StateGraph(EnvImplementState)

            # Add nodes
            workflow.add_node("router", lambda state: state)  # Router node
            workflow.add_node("execute_env", env_repair_execute_node)  # Execute environment commands
            workflow.add_node(
                "analyse_env_error_analyse", env_repair_analyse_node
            )  # Analyze environment errors and generate repair commands
            # workflow.add_node("analyse_env_error_analyse_tools", env_repair_analyse_tool_node)  # File-reading tool
            workflow.add_node("update_command", env_repair_update_command_node)  # Update commands
            workflow.add_node(
                "update_command_tool", env_repair_update_command_tool_node
            )  # Update command tool

            workflow.add_node("check_status", env_repair_check_node)  # Check status

            # Conditionally add nodes based on test_mode
            if test_mode == "pyright":
                workflow.add_node("execute_pyright", env_repair_pyright_execute_node)  # Execute pyright
                workflow.add_node("analyse_pyright_error", env_repair_pyright_analyse_node)  # Analyze pyright errors
                # workflow.add_node(
                #     "update_command", env_repair_update_command_node
                # )  # Update test commands
            elif test_mode == "pytest":
                workflow.add_node("execute_pytest", env_repair_pytest_execute_node)  # 执行pytest
                workflow.add_node("analyse_pytest_error", env_repair_pytest_analyse_node)  # 分析pytest错误
            else:  # In generation mode, in case 3 (environment succeeds but tests have not yet run), tests should be executed
                # workflow.add_node("test_command_adjust_web_search_tool", env_repair_test_command_adjust_web_search_tool_node)  # Adjust test commands
                workflow.add_node("test_command_adjust_node", env_repair_test_command_adjust_node)  # Adjust test commands
                workflow.add_node("test_select_command", env_repair_test_select_command_node)  # Select test commands
                workflow.add_node("execute_test", env_repair_test_execute_node)  # Execute tests
                workflow.add_node("analyse_test_error", env_repair_test_analyse_node)  # Analyze test errors
                # workflow.add_node(
                #     "update_test_command", env_repair_test_update_command_node
                # )  # Update test commands



            # Set entry point
            # For tests, further classify, filter, and enrich based on hierarchy
            if test_mode == "generation":
                workflow.set_entry_point("test_command_adjust_node")
            # workflow.add_conditional_edges(
            #     "test_command_adjust_node",
            #     functools.partial(tools_condition, messages_key="test_command_adjust_messages"),
            #     {
            #         "tools": "test_command_adjust_web_search_tool",
            #         END: "check_status",
            #     },
            # )
            # workflow.add_edge("test_command_adjust_web_search_tool", "test_command_adjust_node")
                workflow.add_edge("test_command_adjust_node", "check_status")
                workflow.add_edge("check_status", "router")
            elif test_mode == "pytest" or test_mode == "pyright":
                workflow.set_entry_point("check_status")
                workflow.add_edge("check_status", "router")

            # Main router: decide next step according to current state
            workflow.add_conditional_edges(
                "router",
                functools.partial(router_function, test_mode=test_mode),
                create_router_mapping(),
            )

            # After executing environment commands, check status
            workflow.add_edge("execute_env", "check_status")
            workflow.add_edge("analyse_env_error_analyse", "update_command")
            # workflow.add_edge("update_command", "update_command_tool")
            workflow.add_conditional_edges(
                "update_command",
                functools.partial(tools_condition, messages_key="env_implement_command_messages"),
                {
                    "tools": "update_command_tool",
                    END: "execute_env",
                },
            )
            workflow.add_edge("update_command_tool", "update_command")
            # Tool execution returns to update_command for continuation
        
            # After executing tests, check status
            
            if test_mode == "pyright":
                # In pyright mode: after executing environment quality checks, check status directly
                workflow.add_edge("execute_pyright", "check_status")
                # If pyright checks fail (issues_count > 0), use the router to analyze errors and generate repair commands
                workflow.add_edge("analyse_pyright_error", "update_command")
                # workflow.add_edge("update_command", "execute_env")
                # Note: routing from update_command to execute_env is handled by conditional edges (lines 186-193), so no extra direct edge is needed
            elif test_mode == "pytest":
                workflow.add_edge("execute_pytest", "check_status")
                workflow.add_edge("analyse_pytest_error", "update_command")
            else:  # In generation mode, case3 (environment succeeded but tests have not yet run) should execute tests
                # workflow.add_edge("test_command_adjust_node", "test_select_command")  # After adjusting test commands, select test commands
                workflow.add_edge("test_select_command", "execute_test")
                workflow.add_edge("execute_test", "check_status")
                workflow.add_edge("analyse_test_error", "update_command")

            # After checking status, decide whether to continue looping
            workflow.add_conditional_edges(
                "check_status",
                check_router_function,
                {
                    "continue": "router",  # Continue looping
                    "end": END,  # End
                },
            )

            # Compile subgraph
            self.subgraph = workflow.compile()




        # if repair_only_run_env_execute:  # Only debug environment bashfile; no need to execute tests
        #     workflow = StateGraph(EnvImplementState)

        #     # Add nodes
        #     workflow.add_node("router", lambda state: state)  # Router node
        #     workflow.add_node("execute_env", env_repair_execute_node)  # Execute environment commands
        #     workflow.add_node(
        #         "analyse_env_error_analyse", env_repair_analyse_node
        #     )  # Analyze environment errors and generate repair commands
        #     # workflow.add_node("analyse_env_error_analyse_tools", env_repair_analyse_tool_node)  # File-reading tool
        #     workflow.add_node("update_command", env_repair_update_command_node)  # Update commands
        #     workflow.add_node(
        #         "update_command_tool", env_repair_update_command_tool_node
        #     )  # Update command tool

        #     workflow.add_node("check_status", env_repair_check_node)  # Check status

        #     # Set entry point
        #     workflow.set_entry_point("check_status")
        #     workflow.add_edge("check_status", "router")

        #     # Main router: decide next step according to current state
        #     workflow.add_conditional_edges(
        #         "router",
        #         functools.partial(router_function, test_mode=test_mode),
        #         create_router_mapping(),
        #     )

        #     # After executing environment commands, check status
        #     workflow.add_edge("execute_env", "check_status")
        #     workflow.add_edge("analyse_env_error_analyse", "update_command")
        #     # workflow.add_edge("update_command", "update_command_tool")
        #     workflow.add_conditional_edges(
        #         "update_command",
        #         functools.partial(tools_condition, messages_key="env_implement_command_messages"),
        #         {
        #             "tools": "update_command_tool",
        #             END: "execute_env",
        #         },
        #     )
        #     workflow.add_edge("update_command_tool", "update_command")
        #     # Tool execution returns to update_command for continuation
        
        #     # After checking status, decide whether to continue looping
        #     workflow.add_conditional_edges(
        #         "check_status",
        #         check_router_function,
        #         {
        #             "continue": "router",  # Continue looping
        #             "end": END,  # End
        #         },
        #     )
        #     # Compile subgraph
        #     self.subgraph = workflow.compile()


    def invoke(
        self,
        input_state: Dict,
        recursion_limit: int = 200,
    ):
        config = {"recursion_limit": recursion_limit}
        output_state = self.subgraph.invoke(input_state, config)
        return output_state
