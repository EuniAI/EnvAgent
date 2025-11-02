"""Node: Update env_implement_command, integrate repair commands"""

import functools
from typing import Dict

from langchain.tools import StructuredTool
from app.utils.logger_manager import get_thread_logger
from app.container.base_container import BaseContainer
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage
from app.tools import file_operation
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

    def __call__(self, state: Dict):
        env_implement_command = state.get("env_implement_command", {})
        env_command = env_implement_command.get("command", "")
        env_implement_result = state.get("env_implement_result", {})
        env_error_analysis = state.get("env_error_analysis", "")
        env_repair_commands = state.get("env_repair_command", [])
        
        # Extract repair commands
        repair_command_list = self._extract_repair_commands(env_repair_commands)
        if not repair_command_list:
            self._logger.warning("No repair commands found, keeping unchanged")
            return {}
        
        # Extract script file path
        script_file_path = self._get_script_relative_path(env_command)
        if not script_file_path:
            self._logger.warning("No script file path found in command")
            return {}
        
        # Build prompt
        repair_commands_text = "\n".join([f"- {cmd}" for cmd in repair_command_list])
        error_analysis_section = f"ENV ERROR ANALYSIS:\n```\n{env_error_analysis}\n```\n\n" if env_error_analysis else ""
        
        # Build execution result section
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
        
        prompt_text = f"""\
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
        
        # Build message history and invoke model with tools
        message_history = [self.system_prompt, HumanMessage(prompt_text)]
        self._logger.info(f"Using model with tools to update script file: {script_file_path}")
        
        # Process tool calls iteratively
        max_iterations = 10
        for iteration in range(max_iterations):
            response = self.model_with_tools.invoke(message_history)
            self._logger.debug(f"Iteration {iteration + 1} response: {response}")
            
            # Add response to message history
            message_history.append(response)
            
            # Check if model wants to call tools
            if not response.tool_calls:
                break
            
            # Execute tool calls
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                
                # Find and execute the tool
                tool = next((t for t in self.tools if t.name == tool_name), None)
                if tool:
                    try:
                        tool_result = tool.invoke(tool_args)
                        tool_message = ToolMessage(
                            content=str(tool_result),
                            tool_call_id=tool_call["id"]
                        )
                        message_history.append(tool_message)
                        self._logger.info(f"Tool {tool_name} executed successfully")
                    except Exception as e:
                        self._logger.error(f"Error executing tool {tool_name}: {str(e)}")
                        tool_message = ToolMessage(
                            content=f"Error: {str(e)}",
                            tool_call_id=tool_call["id"]
                        )
                        message_history.append(tool_message)
        
        # Read updated file content
        updated_content = self._read_updated_file_content(script_file_path)
        
        # Update state
        env_implement_command = {
            "command": env_command,  # Keep original command format
            "file_content": updated_content,
        }
        env_command_result_history = state.get("env_command_result_history", [])
        if len(env_command_result_history) > 0:
            current_env_command_result_history = env_command_result_history[-1]
            current_env_command_result_history['update']=[]
            for msg in message_history:
                if isinstance(msg, AIMessage):
                    tool_calls = msg.tool_calls
                    for tool_call in tool_calls:
                        tool_name = tool_call["name"]
                        tool_args = tool_call["args"]
                        if tool_name == "edit_file":
                            current_env_command_result_history['update'].append(tool_args)
            env_command_result_history[-1] = current_env_command_result_history
        
        env_repair_command = []
        
        return {
            "env_implement_command": env_implement_command,
            "env_repair_command": env_repair_command,
            "env_command_result_history": env_command_result_history
        }
