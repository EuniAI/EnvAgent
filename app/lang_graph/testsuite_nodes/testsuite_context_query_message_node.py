
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph.message import add_messages
from pathlib import Path
from app.lang_graph.states.testsuite_state import TestsuiteState, save_testsuite_states_to_json
from app.utils.logger_manager import get_thread_logger


class TestsuiteContextQueryMessageNode:
    def __init__(self, local_path: Path):
        self._logger, _file_handler = get_thread_logger(__name__)
        self.SYS_PROMPT = (
            "You are an environment verification agent focused on FUNCTIONAL EXECUTABILITY. "
            "Core principle: Level 1 (Entry Points) is the TARGET, Level 3/4 are DIAGNOSTIC tools. "
            "Goal: Find commands from ALL levels (1-4) for comprehensive coverage. Commands will be run strategically later. "
            "Level 1 (Target): Python ('python main.py', 'python -m package'), Node.js ('npm start', 'node server.js'), "
            "Rust ('cargo run'), Go ('go run main.go'); "
            "Level 2 (Integration): 'pytest --integration', 'npm run test:e2e'; "
            "Level 3 (Diagnostic): '<tool> --version', '<tool> --help' - for blocking issues; "
            "Level 4 (Diagnostic): 'pytest -q', 'npm test' - for detailed error info only. "
            "Avoid destructive or long-running commands."
        )
        self.local_path = local_path
    def __call__(self, state: TestsuiteState):
        query_text = state.get(
            "query", "Find one quick verification command from README/docs for this repository."
        )
        human_message = HumanMessage(query_text)
        system_message = SystemMessage(self.SYS_PROMPT)
        self._logger.debug(
            f"Seeding provider messages with system+human for testsuite command discovery:\n{system_message}\n{human_message}"
        )
        # Initialize provider messages with a system prompt and the user query
        state_update = {"testsuite_context_provider_messages": [system_message, human_message]}
        state_for_saving = dict(state)
        state_for_saving["testsuite_context_provider_messages"] = add_messages(
            state.get("testsuite_context_provider_messages", []),
            [system_message, human_message]
        )
        save_testsuite_states_to_json(state_for_saving, self.local_path)
        return state_update
