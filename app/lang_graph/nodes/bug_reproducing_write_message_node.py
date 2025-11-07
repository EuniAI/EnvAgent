
from langchain_core.messages import HumanMessage

from app.lang_graph.states.bug_reproduction_state import BugReproductionState
from app.utils.logger_manager import get_thread_logger


class BugReproducingWriteMessageNode:
    FIRST_HUMAN_PROMPT = """\
{issue_info}

Environment configuration context:
{bug_reproducing_context}

Now find available test commands in the codebase to verify that automatic environment configuration is successful.
"""

    FOLLOWUP_HUMAN_PROMPT = """\
Your previous search didn't find the right test commands. Here is the failure log:
{reproduced_bug_failure_log}

Now search more thoroughly for test commands that can verify environment configuration is working correctly.
"""

    def __init__(self):
        self._logger, _file_handler = get_thread_logger(__name__)

    def format_human_message(self, state: BugReproductionState):
        if "reproduced_bug_failure_log" in state and state["reproduced_bug_failure_log"]:
            return HumanMessage(
                self.FOLLOWUP_HUMAN_PROMPT.format(
                    reproduced_bug_failure_log=state["reproduced_bug_failure_log"],
                )
            )

        return HumanMessage(
            self.FIRST_HUMAN_PROMPT.format(
                bug_reproducing_context="\n\n".join(
                    [str(context) for context in state["bug_reproducing_context"]]
                ),
            )
        )

    def __call__(self, state: BugReproductionState):
        human_message = self.format_human_message(state)
        self._logger.debug(f"Sending message to BugReproducingWriteNode:\n{human_message}")
        return {"bug_reproducing_write_messages": [human_message]}
