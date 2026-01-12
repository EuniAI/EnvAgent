
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages
from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.states.testsuite_state import TestsuiteState, save_testsuite_states_to_json
from app.utils.logger_manager import get_thread_logger


class TestsuiteContextRefineStructuredOutput(BaseModel):
    reasoning: str = Field(description="Your step by step reasoning.")
    refined_query: str = Field(
        "Additional query to ask the ContextRetriever if the context is not enough. Empty otherwise."
    )


class TestsuiteContextRefineNode:
    SYS_PROMPT = """
You are a refinement assistant focused on FUNCTIONAL EXECUTABILITY. Core principle: Level 1 is TARGET, Level 3/4 are DIAGNOSTIC tools.

CRITICAL: This node is the defense line against Repo2Run-style behavior (blindly running unit tests only).

Rule of Thumb (经验法则):
1. Found Level 1 AND at least one other level (2, 3, or 4) has commands → STOP (return empty refined_query) - mission accomplished!
2. Found Level 1 BUT no other levels have commands → Continue searching for other level commands
3. No Level 1 AND steps remaining → Continue searching both docs and code
   - Search docs: README, quickstart, usage sections
   - Search code: entry point files (main.py, app.py, __main__.py, src/main.rs, cmd/*/main.go, etc.)
4. Steps exhausted → STOP (return empty refined_query) - accept what we have

Decision policy (Target-Driven, Multi-Source Diagnostic):
Step 1: Check if Level 1 (Entry Point) exists AND other levels have commands
- If Level 1 found AND (Level 2 OR Level 3 OR Level 4 has commands): STOP (return empty refined_query) - celebrate!
- If Level 1 found BUT no other levels: Continue searching for other level commands (return refined_query)
- If Level 1 NOT found: proceed to Step 2

Step 2: Check remaining steps
- If steps remaining >= 1: Continue searching both docs and code (return refined_query)
- If steps exhausted: STOP (return empty refined_query) - accept current commands

Priority for refined query:
- Search both docs and code comprehensively
- Docs: "Usage", "Quick Start", "Running" sections in README and documentation
- Code: entry point files (main.py, app.py, __main__.py, src/main.rs, cmd/*/main.go)
- Examples: Python ("python main.py"), Node.js ("npm start"), Rust ("cargo run"), Go ("go run main.go")

Note: Level 1 is mandatory. We must try multiple dimensions before giving up.

Avoid: code internals.

Output must follow the structured schema and must NOT contain code fences.
"""

    REFINE_PROMPT = """
Codebase file tree (for orientation):
--- BEGIN FILE TREE ---
{file_tree}
--- END FILE TREE ---

Original user request:
--- BEGIN ORIGINAL QUERY ---
{original_query}
--- END ORIGINAL QUERY ---

Command classification results:
--- BEGIN CLASSIFICATION ---
Build Commands: {build_commands_str}
Level 1 (Entry Point - TARGET): {level1_commands_str}
Level 2 (Integration): {level2_commands_str}
Level 3 (Smoke - Diagnostic): {level3_commands_str}
Level 4 (Unit Test - Diagnostic only): {level4_commands_str}
--- END CLASSIFICATION ---

Remaining search steps: {remaining_steps}

Executability level assessment (Target-Driven Strategy):
- Level 1 (TARGET): Proves real execution - MANDATORY, must find
- Level 2 (Integration): Tests with real deps - OPTIONAL
- Level 3 (Diagnostic): Quick verification for blocking issues - OPTIONAL but useful
- Level 4 (Diagnostic only): May use mocks - OPTIONAL but useful for detailed error info

Rule of Thumb:
1. Found Level 1 AND at least one other level (2, 3, or 4) has commands → STOP (return empty refined_query) - mission accomplished!
2. Found Level 1 BUT no other levels have commands → Continue searching for other level commands (Level 2, 3, or 4)
3. No Level 1 AND steps remaining → Continue searching both docs and code
   - Search docs: README "Usage", "Quick Start", "Running" sections
   - Search code: entry point files (main.py, app.py, __main__.py, src/main.rs, cmd/*/main.go)
4. Steps exhausted → STOP (return empty refined_query) - accept what we have

Decision logic:
1. Check: Does Level 1 exist AND do other levels (2, 3, or 4) have commands?
   - YES (Level 1 exists AND at least one other level has commands) → STOP (return empty refined_query)
   - Level 1 exists BUT no other levels → Continue searching for other level commands (return refined_query)
   - Level 1 NOT found → proceed to step 2

2. Check: Steps remaining?
   - If steps >= 1: Continue searching both docs and code (return refined_query)
   - If steps = 0: STOP (return empty refined_query) - accept current commands

Goal: Follow the Rule of Thumb above. Examples: Python ("python main.py"), Node.js ("npm start"), Rust ("cargo run"), Go ("go run main.go").
"""

    def __init__(self, model: BaseChatModel, kg: KnowledgeGraph, local_path: str, easy_mode: bool = False):
        self.file_tree = kg.get_file_tree()
        self.local_path = local_path
        self.easy_mode = easy_mode
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(TestsuiteContextRefineStructuredOutput)
        self.model = prompt | structured_llm
        self._logger, _file_handler = get_thread_logger(__name__)

    def format_refine_message(self, state: TestsuiteState):
        original_query = state.get("query", "Find a quick verification command from docs")
        
        # Get classified commands by level
        build_commands = state.get("testsuite_build_commands", [])
        level1_commands = state.get("testsuite_level1_commands", [])
        level2_commands = state.get("testsuite_level2_commands", [])
        level3_commands = state.get("testsuite_level3_commands", [])
        level4_commands = state.get("testsuite_level4_commands", [])
        
        # Helper function to extract content from message objects or strings
        def extract_content(cmd):
            if isinstance(cmd, BaseMessage):
                return cmd.content
            return str(cmd)
        
        # Format command strings for each level
        build_commands_str = "\n".join(extract_content(cmd) for cmd in build_commands) if build_commands else "None"
        level1_commands_str = "\n".join(extract_content(cmd) for cmd in level1_commands) if level1_commands else "None"
        level2_commands_str = "\n".join(extract_content(cmd) for cmd in level2_commands) if level2_commands else "None"
        level3_commands_str = "\n".join(extract_content(cmd) for cmd in level3_commands) if level3_commands else "None"
        level4_commands_str = "\n".join(extract_content(cmd) for cmd in level4_commands) if level4_commands else "None"
        
        # Determine remaining steps
        remaining_steps = state.get("testsuite_max_refined_query_loop", 0)
        
        return self.REFINE_PROMPT.format(
            file_tree=self.file_tree,
            original_query=original_query,
            build_commands_str=build_commands_str,
            level1_commands_str=level1_commands_str,
            level2_commands_str=level2_commands_str,
            level3_commands_str=level3_commands_str,
            level4_commands_str=level4_commands_str,
            remaining_steps=remaining_steps,
        )

    def __call__(self, state: TestsuiteState):
        # Check if Level 1 commands have been found AND other levels have commands
        level1_commands = state.get("testsuite_level1_commands", [])
        level2_commands = state.get("testsuite_level2_commands", [])
        level3_commands = state.get("testsuite_level3_commands", [])
        level4_commands = state.get("testsuite_level4_commands", [])
        
        # Easy mode: stop as soon as any testsuite commands exist
        if self.easy_mode:
            has_any_commands = bool(level1_commands or level2_commands or level3_commands or level4_commands)
            if has_any_commands:
                self._logger.info(
                    f"[Easy Mode] Testsuite commands found (Level 1: {bool(level1_commands)}, "
                    f"Level 2: {bool(level2_commands)}, Level 3: {bool(level3_commands)}, "
                    f"Level 4: {bool(level4_commands)}). Stopping refinement."
                )
                return {"testsuite_refined_query": ""}
        
        # Check if we have Level 1 AND at least one other level has commands
        has_level1 = bool(level1_commands)
        has_other_levels = bool(level2_commands or level3_commands or level4_commands)
        
        if has_level1 and has_other_levels:
            self._logger.info(
                f"Level 1 (Entry Point) commands found: {level1_commands}. "
                f"Other levels also have commands (Level 2: {bool(level2_commands)}, "
                f"Level 3: {bool(level3_commands)}, Level 4: {bool(level4_commands)}). "
                "Mission accomplished, stopping refinement."
            )
            return {"testsuite_refined_query": ""}
        
        if has_level1 and not has_other_levels:
            self._logger.info(
                f"Level 1 (Entry Point) commands found: {level1_commands}, "
                "but no other levels have commands. Continuing search for other level commands."
            )
        
        # Check if max loop reached
        if (
            "testsuite_max_refined_query_loop" in state
            and state["testsuite_max_refined_query_loop"] == 0
        ):
            self._logger.info("Reached max_refined_query_loop, not asking for more context")
            return {"testsuite_refined_query": ""}

        human_prompt = self.format_refine_message(state)
        # self._logger.debug(human_prompt)
        response = self.model.invoke({"human_prompt": human_prompt})
        self._logger.debug(response)

        state_update = {"testsuite_refined_query": response.refined_query}

        if "testsuite_max_refined_query_loop" in state:
            state_update["testsuite_max_refined_query_loop"] = (
                state["testsuite_max_refined_query_loop"] - 1
            )

        if response.refined_query:
            state_update["testsuite_context_provider_messages"] = [
                HumanMessage(content=response.refined_query)
            ]

        state_for_saving = dict(state)
        state_for_saving["testsuite_refined_query"] = response.refined_query
        save_testsuite_states_to_json(state_for_saving, self.local_path)
        return state_update
