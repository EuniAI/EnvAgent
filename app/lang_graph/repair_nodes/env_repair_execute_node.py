"""节点：执行环境命令并返回结果"""

import logging
import threading
from typing import Dict

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger
from app.lang_graph.repair_nodes.env_command_utils import extract_command_from_messages


class EnvRepairExecuteNode:
    """执行 env_implement_command 并返回结果"""

    def __init__(self, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: Dict):
        # Extract command from messages (with backward compatibility)
        messages = state.get("env_implement_command_messages", [])
        env_implement_command = extract_command_from_messages(messages, state)
        
        env_repair_command = state.get("env_repair_command", [])
        # 优先运行 env_repair_command
        current_command = env_implement_command.get("command", "")  # 现在默认只运行env_implement_command
        
        if not current_command:
            self._logger.warning("No command found in messages or state")
            return {}
        
        self._logger.info(f"执行环境命令: {current_command}")
        
        # 执行命令
        env_setup_output = self.container.execute_command_with_exit_code(
            current_command
        )
        
        self._logger.info(f"命令执行完成，退出码: {env_setup_output.returncode}")

        # 将env_setup_output转换为字典
        env_result_dict = {
            "returncode": env_setup_output.returncode,
            "stdout": env_setup_output.stdout,
            "stderr": env_setup_output.stderr,
        }
        
        # 获取现有的 env_implement_result 列表（如果有），并追加新结果

        env_command_result_history = state.get("env_command_result_history", []) + [{
            'command': env_implement_command, 
            'result': env_result_dict
        }]
        
        return {
            "env_implement_result": env_result_dict,
            "env_command_result_history": env_command_result_history,
        }

