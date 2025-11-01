"""节点：执行测试命令并返回结果"""

import logging
import threading
from typing import Dict

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger


class EnvRepairTestExecuteNode:
    """执行 test_command 并返回结果"""

    def __init__(self, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: Dict):
        test_command = state.get("test_command", "")
        
        self._logger.info(f"执行测试命令: {test_command}")
        
        # 执行测试命令
        test_output = self.container.execute_command_with_exit_code(
            test_command
        )
        
        self._logger.info(f"测试执行完成，退出码: {test_output.returncode}")
        
        # 将测试结果转换为字典
        test_result_dict = {
            "returncode": test_output.returncode,
            "stdout": test_output.stdout,
            "stderr": test_output.stderr,
        }
        
        # 获取现有的 test_result 列表（如果有），并追加新结果
        existing_test_results = state.get("test_result", [])
        if not isinstance(existing_test_results, list):
            existing_test_results = []
        
        # 追加新结果到列表
        updated_test_results = existing_test_results + [test_result_dict]
        
        return {
            "test_result": updated_test_results,
        }

