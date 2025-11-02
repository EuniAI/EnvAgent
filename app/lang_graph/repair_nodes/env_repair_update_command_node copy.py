"""Node: Update env_implement_command, integrate repair commands"""

import functools
from typing import Dict

from langchain.tools import StructuredTool
from app.utils.logger_manager import get_thread_logger
from app.container.base_container import BaseContainer
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from app.tools import file_operation
import os


class EnvRepairUpdateCommandNode:
    """Update env_implement_command, integrate repair commands"""
    
    SYS_PROMPT = """\
You are a bash scripting expert and environment command update specialist. Modify or update environment implementation commands based on the repair command list, creating optimized environment setup scripts that follow best practices.

Your task is to update or create a bash script file using the edit_file or create_file tool. The script should be complete, executable, and especially designed to run inside Docker containers.

Tools available:
- read_file: Read the content of a file to see the current script
- edit_file: Edit the script file by replacing the entire content with the updated version
- create_file: Create a new script file if the file doesn't exist or if you need to create a new repair script

Bash Script Writing Requirements:
- Follow bash scripting best practices, including error handling and security measures
- Use appropriate error handling and logging
- Make the script idempotent and safe to run multiple times
- Consider Docker container constraints (no sudo, root user, limited system access)
- Install appropriate versions of runtimes and dependencies
- Install all necessary system packages and tools (consider Docker base image limitations)
- Set up project directory structure and permissions correctly
- Configure runtime environment properly for containerized execution
- Set up necessary environment variables and configurations
- Tip 1: Never make a Bash script check or execute itself (e.g., using shellcheck "$0" or bash -n "$0"). Self-invocation can cause recursive parsing and lead to errors like "command substitution: syntax error near unexpected token '||'". Always run syntax checks or linters on an external target file, not on the currently running script.
- Tip 2: Never modify a running Bash script in place (e.g., using sed -i "$0"). Editing the executing file can corrupt the interpreter’s parsing state, cause incorrect line numbers, or trigger syntax errors. Instead, create a copy of the script, apply modifications to that copy, and validate it separately before replacement.


Script Format Requirements:
- Must start with #!/bin/bash
- Use set -e to exit on errors
- Include color output and logging functions (log, error, warning)
- Organize logic into functions, keeping code clear and modular
- Use main function as entry point
- Preserve original script structure and format (if it exists)

Script Update Requirements:
- First, use read_file tool to read the current script file (if it exists)
- Then, use edit_file tool to replace the entire script content with the updated version (if file exists)
- Or use create_file tool to create a new script file (if file doesn't exist or you need a new repair script)
- If input is a script file path, update the existing file or create it if it doesn't exist (preserve original format and structure, but must conform to the above best practices)
- If input is a direct command, convert it to a bash script format that follows best practices
- Suggested filename: "prometheus_setup_repair.sh" or similar repair script name
- Repair commands must be properly integrated without breaking original logic
- The integrated script must be able to solve problems that occurred in previous executions, ensuring repair commands can properly handle errors that caused previous failures
- Maintain command integrity and executability
- Execute tools directly - do not describe tool calls in text


Reference Example Format:
#!/bin/bash

# Exit on any error
set -e

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
}

warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

# Main setup function
main() {
    log "Starting environment setup..."
    # ... integrate original commands and repair commands ...
    log "Environment setup completed successfully!"
}

# Run main function
main "$@"
"""

    def __init__(self, model: BaseChatModel, container: BaseContainer, local_path: str):
        self.container = container
        # self.tools = self._init_tools(local_path)
        # self.model_with_tools = model.bind_tools(self.tools)
        self.model = model
        self.system_prompt = SystemMessage(self.SYS_PROMPT)
        self.local_path = local_path
        self._logger, _file_handler = get_thread_logger(__name__)

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

        create_file_fn = functools.partial(file_operation.create_file, root_path=root_path)
        create_file_tool = StructuredTool.from_function(
            func=create_file_fn,
            name=file_operation.create_file.__name__,
            description=file_operation.CREATE_FILE_DESCRIPTION,
            args_schema=file_operation.CreateFileInput,
        )
        tools.append(create_file_tool)

        return tools

    

    def _extract_file_path(self, command: str) -> str:
        """Extract file path from command"""
        if "bash " in command:
            return command.split("bash ")[-1].strip()
        return command

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

    def _is_file_path(self, command: str) -> bool:
        """Determine if it's a file path"""
        return isinstance(command, str) and (
            command.endswith('.sh') or 
            command.startswith('/') or 
            command.startswith('./')
        )


    def _write_file(self, file_path: str, content: str) -> bool:
        """Write content to file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            with open(file_path, 'w') as f:
                f.write(content)
                return True
        except Exception as e:
            self._logger.error(f"Error writing file {file_path}: {str(e)}")
            return False

    def __call__(self, state: Dict):
        env_implement_command = state.get("env_implement_command", {})
        env_command = env_implement_command.get("command", "")
        env_command_content = env_implement_command.get("file_content", "")
        env_implement_result = state.get("env_implement_result", {})
        env_error_analysis = state.get("env_error_analysis", "")
        env_repair_commands = state.get("env_repair_command", [])
        
        # Extract repair commands
        repair_command_list = self._extract_repair_commands(env_repair_commands)
        if not repair_command_list:
            self._logger.warning("No repair commands found, keeping unchanged")
            return {}
        
        # Extract file path from command
        script_file_path = None
        if env_command and "bash " in env_command:
            script_file_path = env_command.split("bash ")[-1].strip()
            # Remove container path prefix if exists, get relative path
            if script_file_path.startswith("/app/"):
                script_file_path = script_file_path.replace("/app/", "")
        
        # Build prompt
        repair_commands_text = "\n".join([f"- {cmd}" for cmd in repair_command_list])
        file_info = f"Script File Path: {script_file_path}\n\n" if script_file_path else ""
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
            {file_info}{error_analysis_section}{result_section}CURRENT SCRIPT CONTENT:
            ```
            {env_command_content}
            ```

            REPAIR COMMANDS:
            ```
            {repair_commands_text}
            ```

            Please update or create the script file by:
            1. First, use read_file tool to read the current script file ({script_file_path if script_file_path else "the script file"}) if it exists
            2. Then, use edit_file tool to replace the entire script content with the updated version (if file exists), or use create_file tool to create a new script file (if file doesn't exist or you need a new repair script)
            3. The updated/created script should integrate the repair commands properly
            
            Important Requirements:
            1. The integrated new script must be able to solve problems that occurred in previous executions (refer to the above execution results and error analysis), ensuring repair commands can properly handle errors that caused previous failures.
            2. The output script must conform to bash script best practices format:
               - Start with #!/bin/bash
               - Include set -e error handling
               - Include color output and logging functions (log, error, warning)
               - Organize commands into functions, use main function as entry point
               - Keep code clear, modular, and maintainable
               - Add appropriate log output to track execution progress
            3. If the original script already has a good structure, try to preserve it; integrate repair commands appropriately.
        """
        
        # Build message history
        message_history = [self.system_prompt, HumanMessage(prompt_text)]
        
        # Use model with tools to generate updated command
        self._logger.info("Using model with tools to update environment implementation command...")
        response = self.model.invoke(message_history)
        self._logger.debug(response)
        
        # Extract updated file content from tool calls if available
        updated_file_path = "prometheus_setup_repair.sh"
        updated_content = response.content
        
        # If we got content from tool call, update the command
        self._write_file(os.path.join(self.local_path, updated_file_path), updated_content)  # 本地路径
        
        env_implement_command = {
            "command": f'bash /app/{updated_file_path}',  # container 路径
            "file_content": updated_content,
        }
        env_repair_command = []
        return {
            "env_implement_command": env_implement_command,
            "env_repair_command": env_repair_command
        }
        
        
