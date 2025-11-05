"""Node: Update env_implement_command, integrate repair commands"""

import functools
from typing import Dict

from langchain.tools import StructuredTool
from app.utils.logger_manager import get_thread_logger
from app.container.base_container import BaseContainer
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from app.tools import file_operation
from app.lang_graph.repair_nodes.env_command_utils import extract_command_from_messages, store_command_in_message
import os


class EnvRepairUpdateCommandNode:
    """Update env_implement_command, integrate repair commands"""
    
    SYS_PROMPT = """\
You are a bash scripting expert. Your task is to modify ONLY the necessary parts of a bash script based on repair commands, keeping all other parts unchanged.

CRITICAL REQUIREMENTS:
- Use read_file tool to read the current script file first
- Use edit_file tool to make PARTIAL modifications - only change the specific lines/statements that need to be fixed
- DO NOT replace the entire file content - only modify what needs to be changed
- Preserve all unchanged parts of the script exactly as they are
- Each edit_file call should replace a small, specific section with its updated version

IMPORTANT: Line Number Handling:
- read_file returns content with line numbers prefixed (e.g., "33. error ...")
- When using edit_file, you MUST remove the line number prefix from old_content
- The old_content in edit_file must match the ACTUAL file content WITHOUT line numbers
- Example: If read_file shows "33. error \\"msg\\"", use old_content="error \\"msg\\"" (without "33. ")

Tools available:
- read_file: Read the content of a file to see the current script (returns content with line numbers)
- edit_file: Edit specific parts of the script by replacing old_content with new_content (old_content must NOT include line numbers)

Modification Guidelines:
- Identify the specific lines or blocks that need modification based on the repair commands
- Use edit_file to replace only those specific parts
- Ensure old_content in edit_file exactly matches the content in the file WITHOUT line number prefixes (including whitespace)
- Make multiple edit_file calls if you need to modify multiple separate sections
- Do not modify parts that don't need changes
"""

    def __init__(self, model: BaseChatModel, container: BaseContainer, local_path: str):
        self.container = container
        self.model = model
        self.system_prompt = SystemMessage(self.SYS_PROMPT)
        self.local_path = local_path
        self._logger, _file_handler = get_thread_logger(__name__)
        self.tools = self._init_tools(local_path)
        self.model_with_tools = model.bind_tools(self.tools)

    def _init_tools(self, root_path: str):
        """Initialize file operation tools"""
        tools = []

        read_file_fn = functools.partial(file_operation.read_file, root_path=root_path)
        read_file_tool = StructuredTool.from_function(
            func=read_file_fn,
            name=file_operation.read_file.__name__,
            description=file_operation.READ_FILE_DESCRIPTION,
            args_schema=file_operation.ReadFileInput,
        )
        tools.append(read_file_tool)

        edit_file_fn = functools.partial(file_operation.edit_file, root_path=root_path)
        edit_file_tool = StructuredTool.from_function(
            func=edit_file_fn,
            name=file_operation.edit_file.__name__,
            description=file_operation.EDIT_FILE_DESCRIPTION,
            args_schema=file_operation.EditFileInput,
        )
        tools.append(edit_file_tool)

        return tools

    def _extract_repair_commands(self, env_repair_commands) -> list:
        """Extract command content from Context objects"""
        if not isinstance(env_repair_commands, list):
            return []
        
        repair_list = []
        for cmd in env_repair_commands:
            if hasattr(cmd, 'content'):
                repair_list.append(cmd.content)
            elif isinstance(cmd, str):
                repair_list.append(cmd)
            elif isinstance(cmd, dict) and 'content' in cmd:
                repair_list.append(cmd['content'])
        return repair_list

    def _get_script_relative_path(self, env_command: str) -> str:
        """Extract relative script file path from command"""
        if not env_command or "bash " not in env_command:
            return None
        
        script_path = env_command.split("bash ")[-1].strip()
        # Remove container path prefix if exists, get relative path
        if script_path.startswith("/app/"):
            script_path = script_path.replace("/app/", "")
        return script_path

    def _read_updated_file_content(self, relative_path: str) -> str:
        """Read the updated file content after modifications"""
        try:
            file_path = os.path.join(self.local_path, relative_path)
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    return f.read()
        except Exception as e:
            self._logger.error(f"Error reading updated file {relative_path}: {str(e)}")
        return ""

    def _check_all_tool_calls_completed(self, messages: list) -> bool:
        """检查所有工具调用是否都已完成
        
        返回 True 如果：
        1. 没有 AIMessage 有 tool_calls，或者
        2. 所有 AIMessage 的 tool_calls 都有对应的 ToolMessage 响应
        """
        # 收集所有待处理的 tool_call IDs
        pending_tool_call_ids = set()
        completed_tool_call_ids = set()
        
        for msg in messages:
            if isinstance(msg, AIMessage):
                tool_calls = msg.tool_calls or []
                for tool_call in tool_calls:
                    tool_call_id = tool_call.get("id")
                    if tool_call_id:
                        pending_tool_call_ids.add(tool_call_id)
            elif isinstance(msg, ToolMessage):
                tool_call_id = msg.tool_call_id
                if tool_call_id:
                    completed_tool_call_ids.add(tool_call_id)
        
        # 检查是否所有待处理的 tool_calls 都已完成
        all_completed = pending_tool_call_ids.issubset(completed_tool_call_ids)
        
        # 同时检查最后一条消息：如果是 ToolMessage 或没有 tool_calls 的 AIMessage，说明可能已完成
        last_msg = messages[-1] if messages else None
        if last_msg:
            if isinstance(last_msg, ToolMessage):
                # 工具执行完成，检查是否还有待处理的 tool_calls
                return all_completed
            elif isinstance(last_msg, AIMessage):
                # 如果是 AIMessage 且没有 tool_calls，说明已完成
                if not last_msg.tool_calls:
                    return True
                # 如果有 tool_calls，检查是否都已完成
                return all_completed
        
        return all_completed

    def _finalize_update(self, existing_messages: list, env_command: str, state: Dict) -> Dict:
        """完成更新流程：读取文件、更新历史记录、返回最终状态"""
        script_file_path = self._get_script_relative_path(env_command)
        if not script_file_path:
            self._logger.warning(f"Could not extract script path from command: {env_command}")
            return {}
        
        self._logger.info(f"Finalizing update for script: {script_file_path}")
        updated_content = self._read_updated_file_content(script_file_path)
        
        if not updated_content:
            self._logger.warning(f"Could not read updated file content from {script_file_path}, using previous content")
            # 尝试从历史记录中获取
            env_command_result_history = state.get("env_command_result_history", [])
            if env_command_result_history:
                last_command = env_command_result_history[-1].get("command", {})
                updated_content = last_command.get("file_content", "")
        
        if updated_content:
            self._logger.info(f"Successfully read updated file content ({len(updated_content)} characters)")
        else:
            self._logger.error(f"Failed to get file content for {script_file_path}")
        
        final_env_implement_command = {
            "command": env_command,
            "file_content": updated_content,
        }
        
        # Update env_command_result_history
        env_command_result_history = state.get("env_command_result_history", [])
        if len(env_command_result_history) > 0:
            current_env_command_result_history = env_command_result_history[-1]
            if 'update' not in current_env_command_result_history:
                current_env_command_result_history['update'] = []
            for msg in existing_messages:
                if isinstance(msg, AIMessage):
                    tool_calls = msg.tool_calls or []
                    for tool_call in tool_calls:
                        if tool_call.get("name") == "edit_file":
                            current_env_command_result_history['update'].append(tool_call.get("args", {}))
            env_command_result_history[-1] = current_env_command_result_history
        
        # Store command info in message
        completion_msg = store_command_in_message(final_env_implement_command)
        updated_messages = existing_messages + [completion_msg]
        
        return {
            "env_implement_command": final_env_implement_command,
            "env_implement_command_messages": updated_messages,
            "env_repair_command": [],
            "env_command_result_history": env_command_result_history
        }

    def _build_initial_prompt(self, repair_command_list: list, script_file_path: str, 
                             env_error_analysis: str, env_implement_result: Dict) -> str:
        """构建初始提示词"""
        repair_commands_text = "\n".join([f"- {cmd}" for cmd in repair_command_list])
        error_analysis_section = f"ENV ERROR ANALYSIS:\n```\n{env_error_analysis}\n```\n\n" if env_error_analysis else ""
        
        result_section = ""
        if env_implement_result:
            returncode = env_implement_result.get("returncode", "")
            stdout = env_implement_result.get("stdout", "")
            stderr = env_implement_result.get("stderr", "")
            result_section = f"""PREVIOUS EXECUTION RESULT:
            Exit Code: {returncode}

            Standard Output:
            ```
            {stdout}
            ```

            Standard Error:
            ```
            {stderr}
            ```

            """
        
        return f"""\
        {error_analysis_section}{result_section}REPAIR COMMANDS TO INTEGRATE:
        ```
        {repair_commands_text}
        ```

        TARGET SCRIPT FILE: {script_file_path}

        Please modify the script file by:
        1. First, use read_file tool to read the current script file ({script_file_path})
        2. Then, use edit_file tool to make PARTIAL modifications - only change the specific parts that need to be fixed based on the repair commands
        3. Make multiple edit_file calls if you need to modify multiple separate sections
        4. DO NOT replace the entire file - only modify what needs to be changed
        """

    def __call__(self, state: Dict):
        # Extract state
        existing_messages = state.get("env_implement_command_messages", [])
        env_command_info = extract_command_from_messages(existing_messages, state)
        env_command = env_command_info.get("command", "")
        env_implement_result = state.get("env_implement_result", {})
        env_error_analysis = state.get("env_error_analysis", "")
        env_repair_commands = state.get("env_repair_command", [])
        
        # Handle existing messages: check if tool calls are completed
        if existing_messages:
            # 检查所有工具调用是否都已完成
            if self._check_all_tool_calls_completed(existing_messages):
                # 所有工具调用已完成，检查模型是否需要继续对话或已完成
                last_msg = existing_messages[-1]
                if isinstance(last_msg, ToolMessage):
                    # 工具执行完成，让模型决定下一步（可能需要生成新的 tool_calls 或完成）
                    self._logger.info(f"All tool calls completed, getting model response with {len(existing_messages)} messages")
                    response = self.model_with_tools.invoke(existing_messages)
                    
                    # 如果模型没有新的 tool_calls，说明更新完成
                    if isinstance(response, AIMessage) and not response.tool_calls:
                        # 模型已完成，finalize update
                        self._logger.info("Model completed without new tool calls, finalizing update")
                        return self._finalize_update(existing_messages + [response], env_command, state)
                    else:
                        # 模型需要继续工具调用
                        return {
                            "env_implement_command_messages": existing_messages + [response],
                            "env_repair_command": [],
                        }
                elif isinstance(last_msg, AIMessage) and not last_msg.tool_calls:
                    # 最后一条消息是没有 tool_calls 的 AIMessage，说明已完成
                    self._logger.info("No pending tool calls, finalizing update")
                    return self._finalize_update(existing_messages, env_command, state)
            
            # 如果所有工具调用未完成，不应该调用模型，应该等待工具执行
            # 但根据工作流，如果回到这里，工具应该已经执行完成
            # 这种情况不应该发生，但为了安全起见，我们记录警告并尝试继续
            last_msg = existing_messages[-1] if existing_messages else None
            if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                # 还有未完成的 tool_calls，但根据工作流这不应该发生
                # 可能工具节点还没有执行，这种情况不应该调用模型
                self._logger.warning(f"Found pending tool calls in last message, but expected all to be completed. Last message: {type(last_msg).__name__}")
                # 返回空状态，让工作流继续（工具节点应该会处理）
                return {
                    "env_repair_command": [],
                }
            
            # Continue conversation with existing messages
            self._logger.info(f"Continuing conversation with {len(existing_messages)} messages")
            response = self.model_with_tools.invoke(existing_messages)
            return {
                "env_implement_command_messages": existing_messages + [response],
                "env_repair_command": [],
            }
        
        # Initialize new update cycle
        repair_command_list = self._extract_repair_commands(env_repair_commands)
        if not repair_command_list:
            self._logger.warning("No repair commands found, keeping unchanged")
            return {}
        
        script_file_path = self._get_script_relative_path(env_command)
        if not script_file_path:
            self._logger.warning("No script file path found in command")
            return {}
        
        # Build prompt and invoke model
        prompt_text = self._build_initial_prompt(
            repair_command_list, script_file_path, env_error_analysis, env_implement_result
        )
        message_history = [self.system_prompt, HumanMessage(prompt_text)]
        
        self._logger.info(f"Starting update for script file: {script_file_path}")
        response = self.model_with_tools.invoke(message_history)
        
        return {
            "env_implement_command_messages": message_history + [response],
            "env_repair_command": [],
        }
