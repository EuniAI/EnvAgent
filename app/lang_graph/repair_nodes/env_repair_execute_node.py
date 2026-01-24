"""节点：执行环境命令并返回结果"""

from typing import Dict

from app.container.base_container import BaseContainer
from app.lang_graph.repair_nodes.env_command_utils import extract_command_from_messages
from app.utils.logger_manager import get_thread_logger


class EnvRepairExecuteNode:
    """执行 env_implement_command 并返回结果"""

    def __init__(self, container: BaseContainer, ablation_mode: str = None):
        self.container = container
        self.ablation_mode = ablation_mode
        self._logger, _file_handler = get_thread_logger(__name__)

    def _extract_repair_command(self, env_repair_commands) -> str:
        """Extract command content from env_repair_command list"""
        if not isinstance(env_repair_commands, list) or len(env_repair_commands) == 0:
            return ""
        
        # Extract command strings from the list
        repair_list = []
        for cmd in env_repair_commands:
            if isinstance(cmd, str):
                repair_list.append(cmd)
            elif hasattr(cmd, "content"):
                repair_list.append(cmd.content)
            elif isinstance(cmd, dict) and "content" in cmd:
                repair_list.append(cmd["content"])
        
        if not repair_list:
            return ""
        
        # Join multiple commands with && if there are multiple commands
        return " && ".join(repair_list)

    def __call__(self, state: Dict):
        # Extract command from messages (with backward compatibility)
        env_implement_command = state.get("env_implement_command", {})
        env_repair_command = state.get("env_repair_command", [])
        
        # 如果ablation_mode为2，且有env_repair_command，优先运行env_repair_command
        current_command = ""
        if self.ablation_mode == "2" and env_repair_command:
            extracted_command = self._extract_repair_command(env_repair_command)
            if extracted_command:
                current_command = extracted_command
                self._logger.info(f"ablation_mode=2: 优先使用 env_repair_command: {current_command}")
        
        # 如果没有从env_repair_command获取到命令，则使用env_implement_command
        if not current_command:
            current_command = env_implement_command.get("command", "")

        if not current_command:
            self._logger.warning("No command found in messages or state")
            return {}

        self._logger.info(f"执行环境命令: {current_command}")

        # 执行命令，对于环境设置脚本（可能包含 npm install/build 等长时间操作），使用更长的超时时间（30分钟）
        # 默认超时是120秒，但对于 npm install/build 等操作可能需要更长时间
        env_setup_output = self.container.execute_command_with_exit_code(current_command, timeout=1800)

        self._logger.info(f"命令执行完成，退出码: {env_setup_output.returncode}")

        # 将env_setup_output转换为字典
        env_result_dict = {
            "returncode": env_setup_output.returncode,
            "stdout": env_setup_output.stdout,
            "stderr": env_setup_output.stderr,
        }

        # 获取现有的 env_implement_result 列表（如果有），并追加新结果

        env_command_result_history = state.get("env_command_result_history", []) + [
            {"command": env_implement_command, "result": env_result_dict}
        ]

        return {
            "env_implement_result": env_result_dict,
            "env_command_result_history": env_command_result_history,
        }
