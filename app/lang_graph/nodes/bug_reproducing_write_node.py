import functools
import logging
import threading

from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage

from app.lang_graph.states.bug_reproduction_state import BugReproductionState
from app.tools import file_operation
from app.utils.logger_manager import get_thread_logger


class BugReproducingWriteNode:
    SYS_PROMPT = '''\
You are a test automation expert who finds existing test commands in codebases to verify environment configuration.

Your task is to search through the codebase and find available test commands that can verify automatic environment configuration is successful.

Search for:
- Test runner commands (pytest, npm test, go test, cargo test, mvn test, etc.)
- Build scripts with test targets (Makefile, package.json, setup.py, Cargo.toml)
- CI/CD test commands (.github/workflows, .gitlab-ci.yml)
- Docker test services
- Test configuration files

Requirements:
- Find actual test commands that exist in the codebase
- Include command syntax and file locations
- Cover multiple programming languages if present
- Focus on commands that verify basic functionality and environment setup
- Look for environment validation, health checks, and configuration tests

Examples of what to look for:
- Python: pytest, python -m pytest, tox, python -m unittest
- Node.js: npm test, yarn test, jest, npm run test
- Go: go test, go test ./..., go test -v
- Rust: cargo test, cargo check, cargo test --all
- Java: mvn test, gradle test, ./gradlew test
- Makefile: make test, make check, make verify
- Docker: docker-compose test, docker run test

Return the test commands found in the codebase that can verify environment configuration is working correctly.
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

    def __call__(self, state: BugReproductionState):
        message_history = [self.system_prompt] + state["bug_reproducing_write_messages"]
        response = self.model_with_tools.invoke(message_history)

        self._logger.debug(response)
        return {"bug_reproducing_write_messages": [response]}
