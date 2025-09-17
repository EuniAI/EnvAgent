import logging
import threading

from langchain_core.messages import HumanMessage, SystemMessage

from app.lang_graph.states.testsuite_state import TestsuiteState
from app.utils.logger_manager import get_thread_logger


class TestsuiteContextQueryMessageNode:
    def __init__(self):
        self._logger, _file_handler  = get_thread_logger(__name__)
        self.SYS_PROMPT = (
            "You are to discover ONE minimal, safe, and quick verification shell command "
            "from README/docs to confirm the environment/setup works (e.g., '<tool> --version', "
            "'<package> --help', 'make check', 'pytest -q'). Avoid destructive or long-running commands."
        )

    def __call__(self, state: TestsuiteState):
        query_text = state.get("query", "Find one quick verification command from README/docs for this repository.")
        human_message = HumanMessage(query_text)
        system_message = SystemMessage(self.SYS_PROMPT)
        self._logger.debug(
            f"Seeding provider messages with system+human for testsuite command discovery:\n{system_message}\n{human_message}"
        )
        # Initialize provider messages with a system prompt and the user query
        return {"testsuite_context_provider_messages": [system_message, human_message]}
