
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
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
1. Found Level 1 → STOP immediately (return empty refined_query) - mission accomplished!
2. No Level 1 AND steps remaining → Switch dimension and continue searching
   - If currently searching docs → switch to code structure (find main.py, app.py, __main__.py, etc.)
   - If currently searching code → switch to docs (README, quickstart, etc.)
3. Steps exhausted → STOP (return empty refined_query) - accept what we have

Decision policy (Target-Driven, Multi-Source Diagnostic):
Step 1: Check if Level 1 (Entry Point) exists
- If Level 1 found: STOP immediately (return empty refined_query) - celebrate!
- If Level 1 NOT found: proceed to Step 2

Step 2: Check remaining steps
- If steps remaining >= 1: Switch dimension and continue (return refined_query)
- If steps exhausted: STOP (return empty refined_query) - accept current commands

Priority for refined query (when switching dimension):
- From docs to code: Search for entry point files (main.py, app.py, __main__.py, src/main.rs, cmd/*/main.go)
- From code to docs: Search for "Usage", "Quick Start", "Running" sections
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

Found commands:
--- BEGIN COMMANDS ---
{commands_str}
--- END COMMANDS ---

Remaining search steps: {remaining_steps}
Current search dimension: {current_dimension}

Executability level assessment (Target-Driven Strategy):
- Level 1 (TARGET): Proves real execution - MANDATORY, must find
- Level 2 (Integration): Tests with real deps - OPTIONAL
- Level 3 (Diagnostic): Quick verification for blocking issues - OPTIONAL but useful
- Level 4 (Diagnostic only): May use mocks - OPTIONAL but useful for detailed error info

Rule of Thumb (经验法则):
1. Found Level 1 → STOP immediately (return empty refined_query) - mission accomplished!
2. No Level 1 AND steps remaining → Switch dimension and continue
   - If searching docs → switch to code structure (main.py, app.py, __main__.py, src/main.rs, cmd/*/main.go)
   - If searching code → switch to docs (README "Usage", "Quick Start", "Running" sections)
3. Steps exhausted → STOP (return empty refined_query) - accept what we have

Decision logic:
1. Check: Does Level 1 exist?
   - YES → STOP immediately (return empty refined_query)
   - NO → proceed to step 2

2. Check: Steps remaining?
   - If steps >= 1: Switch dimension and continue (return refined_query)
   - If steps = 0: STOP (return empty refined_query) - accept current commands

Goal: Follow the Rule of Thumb above. Examples: Python ("python main.py"), Node.js ("npm start"), Rust ("cargo run"), Go ("go run main.go").
"""

    def __init__(self, model: BaseChatModel, kg: KnowledgeGraph):
        self.file_tree = kg.get_file_tree()
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
        commands = state.get("testsuite_command", [])
        commands_str = "\n".join([c for c in commands if c]) if commands else "No commands found"
        
        # Determine remaining steps
        remaining_steps = state.get("testsuite_max_refined_query_loop", 0)
        
        # Determine current search dimension based on previous queries
        # This is a heuristic - in practice, you might track this in state
        previous_messages = state.get("testsuite_context_provider_messages", [])
        current_dimension = "docs"  # default
        if previous_messages:
            last_query = str(previous_messages[-1].content if hasattr(previous_messages[-1], 'content') else previous_messages[-1])
            if any(keyword in last_query.lower() for keyword in ["main.py", "app.py", "__main__", "src/main", "cmd/"]):
                current_dimension = "code"
            else:
                current_dimension = "docs"
        
        # Determine switch dimension
        switch_dimension = "code structure (main.py, app.py, __main__.py, src/main.rs, cmd/*/main.go)" if current_dimension == "docs" else "docs (README Usage, Quick Start, Running sections)"
        
        return self.REFINE_PROMPT.format(
            file_tree=self.file_tree,
            original_query=original_query,
            commands_str=commands_str,
            remaining_steps=remaining_steps,
            current_dimension=current_dimension,
            switch_dimension=switch_dimension,
        )

    def __call__(self, state: TestsuiteState):
        if (
            "testsuite_max_refined_query_loop" in state
            and state["testsuite_max_refined_query_loop"] == 0
        ):
            self._logger.info("Reached max_refined_query_loop, not asking for more context")
            return {"testsuite_refined_query": ""}

        human_prompt = self.format_refine_message(state)
        self._logger.debug(human_prompt)
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
        state_for_saving["testsuite_refined_query"] = add_messages(
            state.get("testsuite_refined_query", []),
            [response.refined_query]
        )
        save_testsuite_states_to_json(state_for_saving, self.local_path)
        return state_update
