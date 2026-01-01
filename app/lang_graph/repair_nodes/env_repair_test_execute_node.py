"""节点：执行测试命令并返回结果"""

from typing import Dict

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger


class EnvRepairTestExecuteNode:
    """执行 test_command 并返回结果"""

    def __init__(self, container: BaseContainer, test_mode: str):
        self.container = container
        self.test_mode = test_mode
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: Dict):
        selected_test_command = state.get("selected_test_command", "")
        selected_level = state.get("selected_level", "")

        # 判断 test_command 是列表，逐个执行每个命令

        test_output = self.container.execute_command_with_exit_code(selected_test_command)

        self._logger.info(f"命令 {selected_test_command} 执行完成，退出码: {test_output.returncode}")

            # 将测试结果转换为字典
        new_test_results = {
            "command": selected_test_command,  # 记录执行的命令
            "returncode": test_output.returncode,
            "stdout": test_output.stdout,
            "stderr": test_output.stderr,
        }
        test_command_result_history = state.get("test_command_result_history", []) + [
            {
                "level": selected_level,
                "command": selected_test_command,
                "result": new_test_results,
            }
        ]

        # 判断是否需要继续进入 select node
        test_keep_selecting_flag = False
        if selected_level in ["level1", "level2"] and test_output.returncode != 0:
            test_keep_selecting_flag = True
        self._logger.info(f"test_keep_selecting_flag: {test_keep_selecting_flag}")

        return {
            "test_result": new_test_results, 
            "test_command_result_history": test_command_result_history, 
            "test_keep_selecting": test_keep_selecting_flag
            }
