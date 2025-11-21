
from langchain_core.messages import HumanMessage

# from app.lang_graph.states.bug_reproduction_state import BugReproductionState
from app.lang_graph.states.env_implement_state import EnvImplementState
from app.lang_graph.states.env_implement_state import save_env_implement_states_to_json
from app.utils.logger_manager import get_thread_logger


class EnvImplementWriteMessageNode:
    FIRST_HUMAN_PROMPT = """\
Project Environment Context:
{environment_context}


Now generate a complete executable bash script that can successfully set up and configure the environment for this project, especially designed to run inside Docker containers. The bash script should:
1. Install the appropriate runtime and dependencies for the project's technology stack
2. Install all necessary system packages and tools
3. Set up the project directory structure and permissions
4. Configure the runtime environment properly
5. Set up necessary environment variables and configurations
6. Follow bash scripting best practices for error handling and security

Make sure the bash script is self-contained and can set up the project environment from scratch in a Docker container environment.
"""

    FOLLOWUP_HUMAN_PROMPT = """\
Your previous bash script failed to set up or run the project. Here is the failure log:
{testsuites_failure_log}

Now analyze what went wrong and generate an improved bash script that can successfully set up and run this project. Consider:
1. Missing dependencies or system packages
2. Incorrect file paths or working directory setup
3. Environment variable configuration issues
4. Permission or execution problems
5. Runtime compatibility issues

Generate a corrected bash script that addresses these issues.
"""

    def __init__(self, local_path: str):
        self._logger, _file_handler = get_thread_logger(__name__)
        self.local_path = local_path
        
    def format_human_message(self, state: EnvImplementState):
        if "testsuites_failure_log" in state and state["testsuites_failure_log"]:
            return HumanMessage(
                self.FOLLOWUP_HUMAN_PROMPT.format(
                    testsuites_failure_log=state["testsuites_failure_log"],
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
        self._logger.debug(
            f"Sending bash script generation message to EnvImplementWriteNode:\n{human_message}"
        )
        state_update = {"env_implement_write_messages": [human_message]}
        state.update(state_update)
        save_env_implement_states_to_json(state, self.local_path)
        return state_update
