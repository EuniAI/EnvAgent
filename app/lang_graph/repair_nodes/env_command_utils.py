"""Utilities for extracting command information from messages"""

from typing import Dict, List, Optional
from langchain_core.messages import BaseMessage, AIMessage


def extract_command_from_messages(messages: List[BaseMessage], state: Optional[Dict] = None) -> Dict[str, str]:
    """
    从消息中提取命令信息（command 和 file_content）。
    优先从消息中查找，如果找不到则从 env_command_result_history 中获取。
    
    Args:
        messages: 消息列表
        state: 状态字典（可选，用于从历史记录获取）
    
    Returns:
        Dict with keys: 'command' and 'file_content'
    """
    # 方法1: 从消息的 content 中查找特殊标记的命令信息
    # 格式: <command_info>{"command": "...", "file_content": "..."}</command_info>
    for msg in reversed(messages):
        if hasattr(msg, 'content') and isinstance(msg.content, str):
            if '<command_info>' in msg.content and '</command_info>' in msg.content:
                import json
                import re
                match = re.search(r'<command_info>(.*?)</command_info>', msg.content, re.DOTALL)
                if match:
                    try:
                        command_info = json.loads(match.group(1))
                        if isinstance(command_info, dict) and "command" in command_info:
                            return command_info
                    except json.JSONDecodeError:
                        pass
    
    # 方法2: 从消息的 additional_kwargs 中查找（如果存在）
    for msg in reversed(messages):
        if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
            command_info = msg.additional_kwargs.get('_command_info')
            if command_info:
                return command_info
    
    # 方法3: 如果消息中没有，从历史记录中获取
    if state:
        env_command_result_history = state.get("env_command_result_history", [])
        if env_command_result_history:
            last_history = env_command_result_history[-1]
            if isinstance(last_history, dict):
                # 尝试从历史记录的 command 字段获取
                if "command" in last_history:
                    command_dict = last_history["command"]
                    if isinstance(command_dict, dict):
                        return command_dict
                # 尝试从 env_implement_command 字段获取（向后兼容）
                if "env_implement_command" in last_history:
                    command_dict = last_history["env_implement_command"]
                    if isinstance(command_dict, dict):
                        return command_dict
    
    # 方法4: 从 state 中直接获取 env_implement_command（向后兼容）
    if state:
        env_implement_command = state.get("env_implement_command", {})
        if isinstance(env_implement_command, dict) and "command" in env_implement_command:
            return env_implement_command
    
    return {"command": "", "file_content": ""}


def store_command_in_message(command_info: Dict[str, str]) -> AIMessage:
    """
    将命令信息存储在消息中。
    
    Args:
        command_info: 包含 'command' 和 'file_content' 的字典
    
    Returns:
        包含命令信息的 AIMessage
    """
    import json
    
    # 将命令信息序列化为 JSON 并嵌入到消息内容中
    command_json = json.dumps(command_info, ensure_ascii=False)
    content = f"Command update completed.\n<command_info>{command_json}</command_info>"
    
    return AIMessage(
        content=content,
        additional_kwargs={"_command_info": command_info}  # 同时存储在 additional_kwargs 中以便快速访问
    )

