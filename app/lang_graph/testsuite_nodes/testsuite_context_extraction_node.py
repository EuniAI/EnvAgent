
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages
from app.lang_graph.states.testsuite_state import TestsuiteState, save_testsuite_states_to_json
from app.utils.lang_graph_util import (
    extract_last_tool_messages,
)
from app.utils.logger_manager import get_thread_logger

SYS_PROMPT = """
You are a command extractor. Your goal is to extract ALL runnable shell commands found in the documentation.

Requirements:
- Extract ALL suitable commands found in the documentation
- Include commands that start the software, run tests, check versions, etc.
- Do not skip any commands - extract everything you find
- Do not invent commands; only use commands explicitly shown in the documentation
- Return a simple list of commands without classification
- Remove duplicates
"""

HUMAN_MESSAGE = """
Original user intent:
{original_query}

Documentation snippets observed (may contain irrelevant parts):
{context}

Relative path of the Documentation:
{relative_path}

Task: Extract all runnable shell commands from the documentation. Return them as a list without classification.
"""


class TestsuiteCommandStructuredOutput(BaseModel):
    commands: list[str] = Field(
        description="A list of runnable shell commands extracted from the documentation. Empty list if none found."
    )
    reasoning: str = Field(
        description="Brief justification for the extracted commands."
    )


class TestsuiteContextExtractionNode:
    def __init__(self, model: BaseChatModel, local_path: str):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(TestsuiteCommandStructuredOutput)
        self.model = prompt | structured_llm
        self.local_path = local_path
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
            state_update = {"testsuite_command": commands}
            state_for_saving = dict(state)
            state_for_saving["testsuite_command"] = add_messages(
                state.get("testsuite_command", []),
                commands
            )
            save_testsuite_states_to_json(state_for_saving, self.local_path)
            return state_update
        else:
            self._logger.info("No suitable commands found in current snippets")
            return {"testsuite_command": []}
