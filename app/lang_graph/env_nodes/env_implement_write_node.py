import functools
import logging
import threading

from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage

from app.lang_graph.states.env_implement_state import EnvImplementState
from app.tools import file_operation
from app.utils.logger_manager import get_thread_logger


class EnvImplementWriteNode:
    SYS_PROMPT = '''\
You are a Docker expert who creates optimized Dockerfiles for various programming languages and frameworks.
Given project environment context and configuration files, create a complete Dockerfile that can successfully build and run the project.

Requirements:
- Use appropriate base image for the project's technology stack
- Install all necessary dependencies and system packages
- Copy project files and set up working directory correctly
- Configure runtime environment properly
- Expose necessary ports and set up entry point
- Follow Docker best practices for optimization and security
- Use multi-stage builds when beneficial
- Minimize image size and layers
- Handle different project types (web apps, APIs, CLI tools, etc.)

<example>
<project_context>
Python Flask web application with requirements.txt
- Uses Python 3.9+
- Has a requirements.txt with dependencies
- Main application file is app.py
- Runs on port 5000
- Needs to install system packages for some dependencies
</project_context>

<dockerfile>
# Use Python 3.9 slim image as base
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    gcc \\
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Run the application
CMD ["python", "app.py"]
</dockerfile>
</example>

<thought_process>
1. Analyze Project Context:
   - Identify programming language and framework
   - Check for dependency files (requirements.txt, package.json, etc.)
   - Determine runtime requirements
   - Identify entry points and ports

2. Choose Base Image:
   - Select appropriate official base image
   - Consider size and security
   - Match language version requirements

3. Optimize Dockerfile:
   - Use multi-stage builds if beneficial
   - Copy dependency files first for better caching
   - Minimize layers and image size
   - Follow security best practices

4. Configure Runtime:
   - Set working directory
   - Install system dependencies
   - Install application dependencies
   - Set environment variables
   - Expose ports
   - Set entry point
</thought_process>
'''

    def __init__(self, model: BaseChatModel, local_path: str):
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
        return {"env_implement_write_messages": [response]}
