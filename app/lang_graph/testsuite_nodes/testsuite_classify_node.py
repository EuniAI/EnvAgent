"""Test classification node to prevent running unit tests only (like Repo2Run).

This node acts as a critical defense line to ensure we don't blindly run unit tests
when no entry points are found. It classifies commands by level and makes strategic
decisions about what to run.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.lang_graph.states.testsuite_state import TestsuiteState, save_testsuite_states_to_json
from langgraph.graph.message import add_messages
from app.utils.logger_manager import get_thread_logger


class TestClassifyStructuredOutput(BaseModel):
    level1_commands: list[str] = Field(description="List of Level 1 (Entry Point) commands")
    level2_commands: list[str] = Field(description="List of Level 2 (Integration) commands")
    level3_commands: list[str] = Field(description="List of Level 3 (Smoke) commands")
    level4_commands: list[str] = Field(description="List of Level 4 (Unit Test) commands")
    reasoning: str = Field(description="Reasoning for the classification")


SYS_PROMPT = """
You are a test classification agent. Your role is to classify commands by executability level to help prevent blindly running unit tests (Level 4) when no entry points (Level 1) are found - this is a critical defense against Repo2Run-style behavior.

Classify commands by executability level:
Level 1 (Entry Point - TARGET): Commands that start the actual software
- Python: "python main.py", "python -m package", "uvicorn app:app"
- Node.js: "npm start", "node server.js", "npm run dev"
- Rust: "cargo run", "./target/release/app"
- Go: "go run main.go", "./app"

Level 2 (Integration): Tests with real dependencies
- "pytest --integration", "npm run test:e2e", "make integration-test"

Level 3 (Smoke - Diagnostic): Quick verification for blocking issues
- "<tool> --version", "<tool> --help", "make check"

Level 4 (Unit Test - Diagnostic only): May use mocked dependencies
- "pytest -q", "npm test", "cargo test", "go test"

Task: For each command, determine which level (1-4) it belongs to, and organize them into separate lists by level. Provide reasoning for your classification.
"""

HUMAN_MESSAGE = """
Found commands (may be from multiple sources):
--- BEGIN COMMANDS ---
{commands_str}
--- END COMMANDS ---

Task: Classify these commands by executability level (1-4), organize them into separate lists by level, and provide reasoning for your classification.
"""


class TestsuiteClassifyNode:
    """Classifies test commands and prevents blind execution of unit tests only."""

    def __init__(self, model: BaseChatModel, local_path: str):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(TestClassifyStructuredOutput)
        self.model = prompt | structured_llm
        self.local_path = local_path
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: TestsuiteState):
        """
        Classify commands by executability level.
        This is the critical defense line against Repo2Run-style behavior.
        """
        self._logger.info("Starting test classification to prevent blind unit test execution")
        commands = state.get("testsuite_command", [])
        commands_str = "\n".join([c for c in commands if c]) if commands else "No commands found"

        if not commands:
            self._logger.warning("No commands found, cannot proceed")
            return {
                "testsuite_level1_commands": [],
                "testsuite_level2_commands": [],
                "testsuite_level3_commands": [],
                "testsuite_level4_commands": [],
            }

        human_prompt = HUMAN_MESSAGE.format(commands_str=commands_str)
        self._logger.debug(human_prompt)

        try:
            response = self.model.invoke({"human_prompt": human_prompt})
            self._logger.info(
                f"Classification result: Level1={len(response.level1_commands)} commands, "
                f"Level2={len(response.level2_commands)} commands, "
                f"Level3={len(response.level3_commands)} commands, "
                f"Level4={len(response.level4_commands)} commands"
            )
            self._logger.debug(f"Reasoning: {response.reasoning}")
            self._logger.debug(
                f"Level1 commands: {response.level1_commands}\n"
                f"Level2 commands: {response.level2_commands}\n"
                f"Level3 commands: {response.level3_commands}\n"
                f"Level4 commands: {response.level4_commands}"
            )

            state_update = {
                "testsuite_level1_commands": response.level1_commands,
                "testsuite_level2_commands": response.level2_commands,
                "testsuite_level3_commands": response.level3_commands,
                "testsuite_level4_commands": response.level4_commands,
            }
            state_for_saving = dict(state)
            for level in range(1, 5):
                key = f"testsuite_level{level}_commands"
                state_for_saving[key] = add_messages(
                    state.get(key, []),
                    getattr(response, f"level{level}_commands")
                )
            save_testsuite_states_to_json(state_for_saving, self.local_path)
            return state_update
        except Exception as e:
            self._logger.error(f"Error in test classification: {e}")
            # Fallback: if classification fails, be conservative
            return {
                "testsuite_level1_commands": [],
                "testsuite_level2_commands": [],
                "testsuite_level3_commands": [],
                "testsuite_level4_commands": [],
            }

