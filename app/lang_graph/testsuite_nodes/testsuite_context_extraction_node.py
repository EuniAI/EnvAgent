import logging
import threading
from typing import Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.lang_graph.states.testsuite_state import TestsuiteState
from app.utils.logger_manager import get_thread_logger
from app.utils.lang_graph_util import (
    extract_last_tool_messages,
    transform_tool_messages_to_str,
)

SYS_PROMPT = """
You are a command extraction agent. From the provided README/documentation snippets, extract as many runnable shell commands as possible that can verify the environment setup.

Strict requirements:
- Prefer minimal, non-destructive commands that finish quickly (e.g., "<tool> --version", "<package> --help", "make check", "pytest -q", "uv run ... --version")
- Extract ALL suitable commands found in the documentation snippets
- Do not invent commands; only use commands explicitly shown in the docs
- Return a list of command strings in the structured output
- If no suitable commands are present, return an empty list
- Remove duplicate commands and prioritize the most useful ones
"""

HUMAN_MESSAGE = """
Original user intent:
{original_query}

Documentation snippets observed (may contain irrelevant parts):
{context}

Relative path of the Documentation:
{relative_path}

Task: Output multiple safe, quick verification shell commands from the snippets above.
"""


class TestsuiteCommandStructuredOutput(BaseModel):
    commands: list[str] = Field(description="A list of runnable shell commands to verify setup. Empty list if none found.")
    reasoning: str = Field(description="Brief justification for why these commands verify the environment.")


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
        full_context_artifact = extract_last_tool_messages(state["testsuite_context_provider_messages"])[-1].artifact
        for context in full_context_artifact:
            if 'preview' not in context or 'FileNode' not in context:
                continue
            relative_path = context['FileNode']['relative_path']
            preview = context['preview']
            human_messages.append(HUMAN_MESSAGE.format(
                original_query=state.get("query", "Find a quick verification command from docs"),
                context=preview,
                relative_path=relative_path,
            ))
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
