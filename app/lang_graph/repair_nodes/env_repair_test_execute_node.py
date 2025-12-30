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
        test_command = state.get("test_command", "")

        # 获取现有的 test_result 列表（如果有）
        existing_test_results = state.get("test_result", [])

        # 判断 test_command 是列表，逐个执行每个命令
        self._logger.info(f"检测到测试命令列表，共 {len(test_command)} 个命令")

        new_test_results = []
        for idx, cmd in enumerate(test_command):
            # 清理命令字符串（去除换行符和空格）
            cmd = str(cmd).strip()
            if not cmd:
                continue

            self._logger.info(f"执行第 {idx + 1}/{len(test_command)} 个测试命令: {cmd}")

            # 执行测试命令
            test_output = self.container.execute_command_with_exit_code(cmd)

            self._logger.info(f"命令 {idx + 1} 执行完成，退出码: {test_output.returncode}")

            # 将测试结果转换为字典
            test_result_dict = {
                "command": cmd,  # 记录执行的命令
                "returncode": test_output.returncode,
                "stdout": test_output.stdout,
                "stderr": test_output.stderr,
            }
            new_test_results.append(test_result_dict)

        test_command_result_history = state.get("test_command_result_history", []) + [
            {
                "command": test_command,
                "result": new_test_results,
            }
        ]

        return {
            "test_result": new_test_results,
            "test_command_result_history": test_command_result_history,
        }
