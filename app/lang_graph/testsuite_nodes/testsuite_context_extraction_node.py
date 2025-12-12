
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.lang_graph.states.testsuite_state import TestsuiteState
from app.utils.lang_graph_util import (
    extract_last_tool_messages,
)
from app.utils.logger_manager import get_thread_logger

SYS_PROMPT = """
You are a command classifier and extractor. Core principle: Level 1 is TARGET, Level 3/4 are DIAGNOSTIC tools.

Goal: Extract ALL test/command types from ALL levels (1-4) found in the documentation.

Classify each command as:
Level 1 (TARGET - Highest priority): Commands that start the actual software
- Python: "python main.py", "python -m package", "uvicorn app:app"
- Node.js: "npm start", "node server.js", "npm run dev"
- Rust: "cargo run", "./target/release/app"
- Go: "go run main.go", "./app"

Level 2 (Integration): Tests with real dependencies
- "pytest --integration", "npm run test:e2e", "make integration-test"

Level 3 (Diagnostic): Quick verification for blocking issues
- "<tool> --version", "<tool> --help", "make check"

Level 4 (Diagnostic only): For detailed error info, not as repair target
- "pytest -q", "npm test", "cargo test", "go test"

Requirements:
- Extract ALL suitable commands found from ALL levels
- Classify each by level (1-4)
- Do not skip any test commands - extract everything
- Do not invent commands; only use commands explicitly shown
- Return list of commands (prioritized by level, Level 1 first)
- Remove duplicates
"""

HUMAN_MESSAGE = """
Original user intent:
{original_query}

Documentation snippets observed (may contain irrelevant parts):
{context}

Relative path of the Documentation:
{relative_path}

Task: Extract and classify commands by executability level (1=Entry Point, 2=Integration, 3=Smoke, 4=Unit Test). 
Prioritize Level 1-2 commands. Return commands sorted by level (highest first).
"""


class TestsuiteCommandStructuredOutput(BaseModel):
    commands: list[str] = Field(
        description="A list of runnable shell commands to verify setup, sorted by executability level (Level 1-4, highest first). Empty list if none found."
    )
    reasoning: str = Field(
        description="Brief justification including the executability level classification (Level 1=Entry Point, 2=Integration, 3=Smoke, 4=Unit Test) for each command."
    )


class TestsuiteContextExtractionNode:
    def __init__(self, model: BaseChatModel, root_path: str):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(TestsuiteCommandStructuredOutput)
        self.model = prompt | structured_llm
        self.root_path = root_path
        self._logger, file_handler = get_thread_logger(__name__)

    def get_human_messages(self, state: TestsuiteState) -> str:
        # full_context_str = transform_tool_messages_to_str(
        #     extract_last_tool_messages(state["testsuite_context_provider_messages"])
        # )
        # original_query = state.get("query", "Find a quick verification command from docs")
        # return HUMAN_MESSAGE.format(
        #     original_query=original_query,
        #     context=full_context_str,
        # )
        human_messages = []
        _extract = extract_last_tool_messages(state["testsuite_context_provider_messages"])
        if len(_extract) > 0:
            full_context_artifact = _extract[-1].artifact
            for context in full_context_artifact:
                if "preview" not in context or "FileNode" not in context:
                    continue
                relative_path = context["FileNode"]["relative_path"]
                preview = context["preview"]
                human_messages.append(
                    HUMAN_MESSAGE.format(
                        original_query=state.get(
                            "query", "Find a quick verification command from docs"
                        ),
                        context=preview,
                        relative_path=relative_path,
                    )
                )
        return human_messages

    def __call__(self, state: TestsuiteState):
        """
        Extract a single verification command from documentation snippets gathered by the provider tools.
        """
        self._logger.info("Starting testsuite command extraction process")
        existing_command = state.get("testsuite_command", "")
        if existing_command:
            self._logger.info("Command already present in state; skipping extraction")
            return {"testsuite_command": existing_command}
        human_messages = self.get_human_messages(state)
        self._logger.debug(human_messages)
        all_commands = []
        for human_message in human_messages:
            response = self.model.invoke({"human_prompt": human_message})
            self._logger.debug(f"Model response: {response}")
            commands = response.commands or []
            # Filter out empty commands and add to the list
            for command in commands:
                command = command.strip()
                if command:  # del blank command
                    all_commands.append(command)
        # Remove duplicates while preserving order
        commands = list(dict.fromkeys(all_commands))

        if commands:
            self._logger.info(f"Extracted verification commands: {commands}")
            return {"testsuite_command": commands}
        else:
            self._logger.info("No suitable commands found in current snippets")
            return {"testsuite_command": []}
