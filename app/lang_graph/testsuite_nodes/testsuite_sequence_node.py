"""Test sequence node implementing "Funnel Defense" strategy.

This node orders test commands in an optimal execution sequence:
Level 3 (Smoke) -> Level 1 (Entry) -> Level 2 (Integration) -> Level 4 (Unit)

This maximizes efficiency by failing fast and short-circuiting on success.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.lang_graph.states.testsuite_state import TestsuiteState
from app.utils.logger_manager import get_thread_logger


class ExecutionStep(BaseModel):
    order: int = Field(description="Execution order (1, 2, 3...)")
    command: str = Field(description="The shell command")
    original_level: int = Field(description="The extracted level (1-4)")
    phase_name: str = Field(
        description="Phase name: Pre-flight / Primary / Fallback / Diagnostic"
    )
    stop_on_success: bool = Field(
        description="If true, stop the entire agent if this command succeeds (True for Level 1)"
    )
    is_blocking: bool = Field(
        description="If true, stop the entire agent if this command fails (True for Level 3)"
    )


class ExecutionPlan(BaseModel):
    queue: list[ExecutionStep] = Field(description="Ordered list of commands to execute")
    reasoning: str = Field(description="Reasoning for the execution sequence")


SYS_PROMPT = """
You are the Execution Sequence Planner for an environment verification agent.

Your goal is to order the extracted commands to verify "Functional Executability" efficiently using the "Funnel Defense" strategy.

STRATEGY: "Pre-flight Check -> Main Target -> Fallback -> Diagnostic"

SORTING RULES (Strict Priority):

1. **PHASE 1: PRE-FLIGHT (Level 3 - Smoke Tests)**
   - MUST run first
   - Purpose: Verify basic tool existence (e.g., `--version`, `import pkg`, `--help`)
   - Rationale: Fail fast if the environment is fundamentally broken
   - is_blocking: True (if this fails, stop everything)
   - stop_on_success: False
   - Examples: Python ("python --version", "python -c 'import package'"), Node.js ("node --version"), Rust ("cargo --version"), Go ("go version")

2. **PHASE 2: PRIMARY TARGET (Level 1 - Main Entry Points)**
   - MUST run second (if Phase 1 passes)
   - Purpose: Verify the software actually starts (e.g., `python main.py`, `npm start`)
   - Rationale: This is the GOLD STANDARD. If this succeeds, the task is DONE
   - is_blocking: False
   - stop_on_success: True (if this succeeds, stop everything - mission accomplished)
   - Examples: Python ("python main.py", "python -m package", "uvicorn app:app"), Node.js ("npm start", "node server.js"), Rust ("cargo run"), Go ("go run main.go")

3. **PHASE 3: ROBUSTNESS CHECK (Level 2 - Integration Tests)**
   - Run third (only if Level 1 is missing or fails)
   - Purpose: Verify dependencies in a test harness
   - is_blocking: False
   - stop_on_success: False
   - Examples: "pytest --integration", "npm run test:e2e", "make integration-test"

4. **PHASE 4: DIAGNOSTIC (Level 4 - Unit Tests)**
   - Run last
   - Purpose: Debugging only. Do not rely on this for environment verification unless absolutely necessary
   - is_blocking: False
   - stop_on_success: False
   - Examples: "pytest -q", "npm test", "cargo test", "go test"

INSTRUCTIONS:
- Remove duplicate commands
- If multiple commands exist for Level 1, prioritize the one that looks most like a "Start Server" or "CLI Entry" command over generic scripts
- Assign order numbers starting from 1
- Set phase_name according to the level: Level 3="Pre-flight", Level 1="Primary", Level 2="Fallback", Level 4="Diagnostic"
- Set stop_on_success=True only for Level 1 commands
- Set is_blocking=True only for Level 3 commands
- Output an ordered list where the order represents the execution sequence
"""

HUMAN_MESSAGE = """
Here are the discovered commands (with their original levels from classification):

{commands_with_levels}

Please reorder them into an optimal execution sequence based on the "Funnel Defense" strategy:
1. Pre-flight (Level 3) - first, blocking
2. Primary Target (Level 1) - second, stops on success
3. Fallback (Level 2) - third
4. Diagnostic (Level 4) - last

Remove duplicates and prioritize commands that best represent each phase.
"""


class TestsuiteSequenceNode:
    """Orders test commands using Funnel Defense strategy."""

    def __init__(self, model: BaseChatModel):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(ExecutionPlan)
        self.model = prompt | structured_llm
        self._logger, _file_handler = get_thread_logger(__name__)

    def _classify_command_level(self, command: str) -> int:
        """
        Heuristic classification of command level.
        This is a fallback if classification info is not available.
        """
        command_lower = command.lower()
        
        # Level 1: Entry points
        if any(
            keyword in command_lower
            for keyword in [
                "python main.py",
                "python -m",
                "npm start",
                "node server",
                "cargo run",
                "go run",
                "uvicorn",
                "flask run",
            ]
        ):
            return 1
        
        # Level 2: Integration tests
        if any(
            keyword in command_lower
            for keyword in ["--integration", "test:e2e", "integration-test"]
        ):
            return 2
        
        # Level 3: Smoke tests
        if any(
            keyword in command_lower
            for keyword in ["--version", "--help", "make check", "import"]
        ):
            return 3
        
        # Level 4: Unit tests (default)
        if any(
            keyword in command_lower
            for keyword in ["pytest", "npm test", "cargo test", "go test", "make test"]
        ):
            return 4
        
        # Default to Level 4 if unclear
        return 4

    def _format_commands_with_levels(
        self, commands: list[str], state: TestsuiteState
    ) -> str:
        """Format commands with their levels for the prompt."""
        lines = []
        for cmd in commands:
            if not cmd or not cmd.strip():
                continue
            # Try to infer level from command
            level = self._classify_command_level(cmd)
            lines.append(f"Level {level}: {cmd}")
        return "\n".join(lines) if lines else "No commands found"

    def __call__(self, state: TestsuiteState):
        """
        Order commands using Funnel Defense strategy.
        """
        self._logger.info("Starting test sequence planning with Funnel Defense strategy")
        commands = state.get("testsuite_command", [])

        if not commands:
            self._logger.warning("No commands found, cannot create execution plan")
            return {"testsuite_execution_plan": []}

        # Remove duplicates while preserving order
        unique_commands = list(dict.fromkeys([c.strip() for c in commands if c.strip()]))

        commands_with_levels = self._format_commands_with_levels(unique_commands, state)
        human_prompt = HUMAN_MESSAGE.format(commands_with_levels=commands_with_levels)
        self._logger.debug(human_prompt)

        try:
            response = self.model.invoke({"human_prompt": human_prompt})
            self._logger.info(
                f"Created execution plan with {len(response.queue)} steps"
            )
            self._logger.debug(f"Reasoning: {response.reasoning}")
            
            # Log the sequence
            for step in response.queue:
                self._logger.debug(
                    f"Step {step.order}: {step.command} "
                    f"(Level {step.original_level}, Phase: {step.phase_name}, "
                    f"Blocking: {step.is_blocking}, StopOnSuccess: {step.stop_on_success})"
                )

            # Convert to dict format for state
            execution_plan = [
                {
                    "order": step.order,
                    "command": step.command,
                    "original_level": step.original_level,
                    "phase_name": step.phase_name,
                    "stop_on_success": step.stop_on_success,
                    "is_blocking": step.is_blocking,
                }
                for step in response.queue
            ]

            return {"testsuite_execution_plan": execution_plan}
        except Exception as e:
            self._logger.error(f"Error in test sequence planning: {e}")
            # Fallback: create a simple ordered list by level (3->1->2->4)
            fallback_plan = []
            order = 1
            for level in [3, 1, 2, 4]:
                for cmd in unique_commands:
                    cmd_level = self._classify_command_level(cmd)
                    if cmd_level == level:
                        phase_map = {3: "Pre-flight", 1: "Primary", 2: "Fallback", 4: "Diagnostic"}
                        fallback_plan.append(
                            {
                                "order": order,
                                "command": cmd,
                                "original_level": level,
                                "phase_name": phase_map[level],
                                "stop_on_success": level == 1,
                                "is_blocking": level == 3,
                            }
                        )
                        order += 1
            self._logger.warning(f"Using fallback plan with {len(fallback_plan)} steps")
            return {"testsuite_execution_plan": fallback_plan}

