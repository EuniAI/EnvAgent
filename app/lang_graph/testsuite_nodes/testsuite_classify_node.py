"""Test classification node to prevent running unit tests only (like Repo2Run).

This node acts as a critical defense line to ensure we don't blindly run unit tests
when no entry points are found. It classifies commands by level and makes strategic
decisions about what to run.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.lang_graph.states.testsuite_state import TestsuiteState
from app.utils.logger_manager import get_thread_logger


class TestClassifyStructuredOutput(BaseModel):
    has_level1: bool = Field(description="Whether Level 1 (Entry Point) commands exist")
    has_level2: bool = Field(description="Whether Level 2 (Integration) commands exist")
    has_level3: bool = Field(description="Whether Level 3 (Smoke) commands exist")
    has_level4: bool = Field(description="Whether Level 4 (Unit Test) commands exist")
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

Task: Classify each command by determining which level it belongs to (1-4). Provide reasoning for your classification.
"""

HUMAN_MESSAGE = """
Found commands (may be from multiple sources):
--- BEGIN COMMANDS ---
{commands_str}
--- END COMMANDS ---

Task: Classify these commands by executability level (1-4) and provide reasoning.
"""


class TestsuiteClassifyNode:
    """Classifies test commands and prevents blind execution of unit tests only."""

    def __init__(self, model: BaseChatModel):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(TestClassifyStructuredOutput)
        self.model = prompt | structured_llm
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
                "testsuite_has_level1": False,
                "testsuite_has_level2": False,
                "testsuite_has_level3": False,
                "testsuite_has_level4": False,
            }

        human_prompt = HUMAN_MESSAGE.format(commands_str=commands_str)
        self._logger.debug(human_prompt)

        try:
            response = self.model.invoke({"human_prompt": human_prompt})
            self._logger.info(
                f"Classification result: Level1={response.has_level1}, "
                f"Level2={response.has_level2}, Level3={response.has_level3}, "
                f"Level4={response.has_level4}"
            )
            self._logger.debug(f"Reasoning: {response.reasoning}")

            return {
                "testsuite_has_level1": response.has_level1,
                "testsuite_has_level2": response.has_level2,
                "testsuite_has_level3": response.has_level3,
                "testsuite_has_level4": response.has_level4,
            }
        except Exception as e:
            self._logger.error(f"Error in test classification: {e}")
            # Fallback: if classification fails, be conservative
            return {
                "testsuite_has_level1": False,
                "testsuite_has_level2": False,
                "testsuite_has_level3": False,
                "testsuite_has_level4": False,
            }

