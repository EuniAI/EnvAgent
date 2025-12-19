
from app.lang_graph.states.env_implement_state import EnvImplementState
from app.utils.logger_manager import get_thread_logger
from langchain_core.messages import HumanMessage
from typing import Optional, Sequence


class EnvImplementFileContextMessageNode:
    ENV_IMPLEMENT_FILE_CONTEXT_QUERY_TEMPLATE = """\
OBJECTIVE: Find environment configuration files needed to generate a Dockerfile that can successfully run the testsuite commands.

TESTSUITE COMMANDS:
{test_commands_section}

Based on the testsuite commands above, find files that:
1. Define dependencies required by the testsuite (requirements.txt, package.json, go.mod, Cargo.toml, etc.)
2. Configure build systems (Makefile, CMakeLists.txt, build.gradle, etc.)
3. Set up runtime environments (.env, config files, Dockerfile, docker-compose.yml)
4. Contain installation/setup instructions (README.md, INSTALL.md, SETUP.md)

REQUIREMENTS:
- Return complete file content with exact file paths and line numbers
- Focus on files directly related to running the testsuite commands
- Include any existing Docker-related files for reference
"""

    def __init__(self, debug_mode: bool, test_mode: str = "generation"):
        self.debug_mode = debug_mode
        self.test_mode = test_mode
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: EnvImplementState):
        # Get testsuite commands from state or self.test_commands based on test_mode
        test_commands_section = ""
        
        if self.test_mode == "pyright":
            # pyright mode: 不输入 test
            test_commands_section = "No testsuite commands provided. Search for general environment configuration files."
        elif self.test_mode in ["CI/CD", "pytest"]:
            # cicd and pytest mode: 输入全部 test
            test_commands = []
            
            # Try to get from state first (testsuite_commands or test_command)
            testsuite_commands = state.get("testsuite_commands")
            if testsuite_commands:
                if isinstance(testsuite_commands, list):
                    test_commands = [str(cmd) for cmd in testsuite_commands]
                else:
                    test_commands = [str(testsuite_commands)]
            
            # Fallback to self.test_commands if not in state
            if not test_commands and self.test_commands:
                if isinstance(self.test_commands, list):
                    test_commands = [str(cmd) for cmd in self.test_commands]
                else:
                    test_commands = [str(self.test_commands)]
            
            # Format all test commands
            if test_commands:
                test_commands_section = "ALL TEST COMMANDS:\n" + "\n".join([f"- {cmd}" for cmd in test_commands])
            else:
                test_commands_section = "No testsuite commands provided. Search for general environment configuration files."
        elif self.test_mode == "generation":
            # generation mode: 按照 level1-4 的类别输入，并且要解释清楚含义，按照 level1-4 的优先级来寻找配置文件
            testsuite_commands = state.get("testsuite_commands", {})
            if not testsuite_commands and self.test_commands:
                testsuite_commands = self.test_commands
            
            # Extract level commands from dictionary
            level1_commands = []
            level2_commands = []
            level3_commands = []
            level4_commands = []
            
            if isinstance(testsuite_commands, dict):
                level1_commands = testsuite_commands.get("level1_commands", [])
                level2_commands = testsuite_commands.get("level2_commands", [])
                level3_commands = testsuite_commands.get("level3_commands", [])
                level4_commands = testsuite_commands.get("level4_commands", [])
            
            # Format commands by level with explanations
            sections = []
            
            if level1_commands:
                sections.append(
                    "Level 1 (Entry Point - TARGET - HIGHEST PRIORITY):\n"
                    "These commands start the actual software (e.g., 'python main.py', 'npm start', 'cargo run').\n"
                    "Find configuration files needed to run these commands:\n" +
                    "\n".join([f"  - {cmd}" for cmd in level1_commands])
                )
            
            if level2_commands:
                sections.append(
                    "Level 2 (Integration Tests - SECOND PRIORITY):\n"
                    "These are integration tests with real dependencies (e.g., 'pytest --integration').\n"
                    "Find configuration files needed for integration testing:\n" +
                    "\n".join([f"  - {cmd}" for cmd in level2_commands])
                )
            
            if level3_commands:
                sections.append(
                    "Level 3 (Smoke Tests - Diagnostic - THIRD PRIORITY):\n"
                    "These are quick verification commands for blocking issues (e.g., '--version', '--help', 'make check').\n"
                    "Find configuration files needed for smoke testing:\n" +
                    "\n".join([f"  - {cmd}" for cmd in level3_commands])
                )
            
            if level4_commands:
                sections.append(
                    "Level 4 (Unit Tests - Diagnostic only - LOWEST PRIORITY):\n"
                    "These may use mocked dependencies (e.g., 'pytest -q', 'npm test', 'cargo test').\n"
                    "Find configuration files needed for unit testing:\n" +
                    "\n".join([f"  - {cmd}" for cmd in level4_commands])
                )
            
            if sections:
                test_commands_section = "\n\n".join(sections)
                test_commands_section += (
                    "\n\nSEARCH PRIORITY: Focus on Level 1 files first, then Level 2, then Level 3, "
                    "and finally Level 4. Level 1 commands are the most critical for environment setup."
                )
            else:
                test_commands_section = "No testsuite commands provided. Search for general environment configuration files."
        else:
            # Default: no test commands
            test_commands_section = "No testsuite commands provided. Search for general environment configuration files."
        
        # Build the query with testsuite commands
        env_implement_file_context_query = self.ENV_IMPLEMENT_FILE_CONTEXT_QUERY_TEMPLATE.format(
            test_commands_section=test_commands_section
        )
        
        self._logger.debug(
            f"Sending environment configuration query to context provider subgraph:\n{env_implement_file_context_query}"
        )

        return {
            "env_implement_file_context_query": env_implement_file_context_query,
            "context_provider_messages": [HumanMessage(env_implement_file_context_query)],
        }
