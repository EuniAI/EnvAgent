import functools

from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage

from app.lang_graph.states.env_implement_state import EnvImplementState, save_env_implement_states_to_json
from app.tools import file_operation
from app.utils.logger_manager import get_thread_logger


class EnvImplementWriteNode:
    SYS_PROMPT = """\
You are a bash scripting expert who creates optimized environment setup scripts for various programming languages and frameworks.
Given project environment context and configuration files, create a complete executable bash script that can successfully set up and configure the project environment, especially designed to run inside Docker containers.

Requirements:
- Install appropriate runtime and dependencies for the project's technology stack
- Install all necessary system packages and tools (consider Docker base image limitations)
- Set up project directory structure and permissions correctly
- Configure runtime environment properly for containerized execution
- Set up necessary environment variables and configurations
- Follow bash scripting best practices for error handling and security
- Use proper error handling and logging
- Make the script idempotent and safe to run multiple times
- Handle different project types (web apps, APIs, CLI tools, etc.)
- Consider Docker container constraints (no sudo, root user, limited system access)

<example>
<project_context>
Python Flask web application with requirements.txt
- Uses Python 3.9+
- Has a requirements.txt with dependencies
- Main application file is app.py
- Runs on port 5000
- Needs to install system packages for some dependencies
</project_context>

<bash_script>
#!/bin/bash

# Exit on any error
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

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

# Check if Python 3.9+ is installed
check_python() {
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        log "Python $PYTHON_VERSION found"
    else
        error "Python 3.9+ is required but not installed"
        exit 1
    fi
}

# Install system dependencies
install_system_deps() {
    log "Installing system dependencies..."
    apt-get update
    apt-get install -y gcc python3-dev python3-pip
    log "System dependencies installed"
}

# Set up virtual environment
setup_venv() {
    log "Setting up Python virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    log "Virtual environment created and activated"
}

# Install Python dependencies
install_deps() {
    log "Installing Python dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
    log "Python dependencies installed"
}

# Set environment variables
setup_env() {
    log "Setting up environment variables..."
    export FLASK_APP=app.py
    export FLASK_ENV=production
    export FLASK_RUN_PORT=5000
    log "Environment variables set"
}

# Main setup function
main() {
    log "Starting Flask application environment setup..."
    
    check_python
    install_system_deps
    setup_venv
    install_deps
    setup_env
    
    log "Environment setup completed successfully!"
    log "To run the application: source venv/bin/activate && python app.py"
}

# Run main function
main "$@"
</bash_script>
</example>

<thought_process>
1. Analyze Project Context:
   - Identify programming language and framework
   - Check for dependency files (requirements.txt, package.json, etc.)
   - Determine runtime requirements
   - Identify entry points and ports

2. Plan Environment Setup:
   - Determine required system packages
   - Plan dependency installation order
   - Consider version compatibility
   - Plan for error handling and rollback

3. Optimize Bash Script:
   - Use proper error handling (set -e, trap)
   - Add logging and progress indicators
   - Make script idempotent and safe to re-run
   - Follow security best practices

4. Configure Environment:
   - Set up working directory
   - Install system dependencies
   - Install application dependencies
   - Set environment variables
   - Configure permissions and ownership
   - Provide clear usage instructions
</thought_process>
"""

    def __init__(self, model: BaseChatModel, local_path: str):
        self.local_path = local_path
        self.tools = self._init_tools(local_path)
        self.system_prompt = SystemMessage(self.SYS_PROMPT)
        self.model_with_tools = model.bind_tools(self.tools)
        self._logger, _file_handler = get_thread_logger(__name__)

    def _init_tools(self, root_path: str):
        """Initializes file operation tools with the given root path.

        Args:
          root_path: Base directory path for all file operations.

        Returns:
          List of StructuredTool instances configured for file operations.
        """
        tools = []

        read_file_fn = functools.partial(file_operation.read_file, root_path=root_path)
        read_file_tool = StructuredTool.from_function(
            func=read_file_fn,
            name=file_operation.read_file.__name__,
            description=file_operation.READ_FILE_DESCRIPTION,
            args_schema=file_operation.ReadFileInput,
        )
        tools.append(read_file_tool)

        return tools

    def __call__(self, state: EnvImplementState):
        message_history = [self.system_prompt] + state["env_implement_write_messages"]
        response = self.model_with_tools.invoke(message_history)

        self._logger.debug(response)
        state_update = {"env_implement_write_messages": [response]}
        save_env_implement_states_to_json(state_update, self.local_path)
        return state_update
