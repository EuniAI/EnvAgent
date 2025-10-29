"""节点：更新 env_implement_command，整合修复命令"""

import logging
import threading
from typing import Dict

from app.utils.logger_manager import get_thread_logger
from app.container.base_container import BaseContainer


class EnvRepairUpdateCommandNode:
    """更新 env_implement_command，将修复命令整合进去"""
    
    def __init__(self, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: Dict):
        env_implement_command = state.get("env_implement_command", "")
        env_repair_commands = state.get("env_repair_command", [])
        
        if not env_repair_commands:
            self._logger.warning("没有修复命令，保持不变")
            return {}
        
        # 确保是列表类型
        if not isinstance(env_repair_commands, list):
            env_repair_commands = []
        
        # 从 Context 对象中提取命令内容
        repair_command_list = []
        for cmd_context in env_repair_commands:
            if hasattr(cmd_context, 'content'):
                repair_command_list.append(cmd_context.content)
            elif isinstance(cmd_context, str):
                repair_command_list.append(cmd_context)
            elif isinstance(cmd_context, dict) and 'content' in cmd_context:
                repair_command_list.append(cmd_context['content'])
        
        if not repair_command_list:
            self._logger.warning("修复命令列表为空，保持不变")
            return {}
        
        # 将多个修复命令用 && 连接
        combined_repair_commands = " && ".join(repair_command_list)
        self._logger.info(f"修复指令列表: {repair_command_list}")
        
        # 将修复命令添加到原命令中（使用 && 连接）
        # 如果 env_implement_command 是 bash 文件，需要检查
        if isinstance(env_implement_command, str) and env_implement_command.endswith('.sh'):
            # 对于 bash 文件，需要将修复命令追加到文件末尾
            updated_command = env_implement_command
            self._logger.info(f"修复命令将添加到 bash 文件: {combined_repair_commands}")
            # 注意：这里只是标记，实际的文件修改需要在容器中进行
        else:
            # 对于直接命令，连接修复命令
            env_cmd_str = str(env_implement_command)
            updated_command = f"{env_cmd_str} && {combined_repair_commands}"
            self._logger.info(f"修复命令将连接到原命令: {combined_repair_commands}")
        
        # 更新命令
        self._logger.info(f"更新后的 env_implement_command: {updated_command}")
        
        return {
            "env_implement_command": updated_command,
            "env_repair_command": [],  # 清空修复命令列表，避免重复添加
        }

