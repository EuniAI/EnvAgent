import logging
import threading

from langchain_core.messages import HumanMessage

# from app.lang_graph.states.bug_reproduction_state import BugReproductionState
from app.lang_graph.states.env_implement_state import EnvImplementState
from app.utils.logger_manager import get_thread_logger


class EnvImplementWriteMessageNode:
    FIRST_HUMAN_PROMPT = """\
Project Environment Context:
{environment_context}


Now generate a complete Dockerfile that can successfully build and run this project. The Dockerfile should:
1. Use the appropriate base image for the project's technology stack
2. Install all necessary dependencies and system packages
3. Copy project files and set up the working directory
4. Configure the runtime environment properly
5. Expose necessary ports and set up the entry point
6. Follow Docker best practices for optimization and security

Make sure the Dockerfile is self-contained and can build the project from scratch.
"""

    FOLLOWUP_HUMAN_PROMPT = """\
Your previous Dockerfile failed to build or run the project. Here is the failure log:
{dockerfile_failure_log}

Now analyze what went wrong and generate an improved Dockerfile that can successfully build and run this project. Consider:
1. Missing dependencies or system packages
2. Incorrect file paths or working directory setup
3. Environment variable configuration issues
4. Port configuration or entry point problems
5. Base image compatibility issues

Generate a corrected Dockerfile that addresses these issues.
"""

    def __init__(self):
        self._logger, _file_handler = get_thread_logger(__name__)

    def format_human_message(self, state: EnvImplementState):
        if "dockerfile_failure_log" in state and state["dockerfile_failure_log"]:
            return HumanMessage(
                self.FOLLOWUP_HUMAN_PROMPT.format(
                    dockerfile_failure_log=state["dockerfile_failure_log"],
                )
            )

        return HumanMessage(
            self.FIRST_HUMAN_PROMPT.format(
                environment_context="\n\n".join(
                    [str(context) for context in state.get("env_implement_file_context", [])]
                )
            )
        )

    def __call__(self, state: EnvImplementState):
        human_message = self.format_human_message(state)
        self._logger.debug(f"Sending Dockerfile generation message to EnvImplementWriteNode:\n{human_message}")
        return {"env_implement_write_messages": [human_message]}
