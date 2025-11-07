
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.states.testsuite_state import TestsuiteState
from app.utils.logger_manager import get_thread_logger


class TestsuiteContextRefineStructuredOutput(BaseModel):
    reasoning: str = Field(description="Your step by step reasoning.")
    refined_query: str = Field(
        "Additional query to ask the ContextRetriever if the context is not enough. Empty otherwise."
    )


class TestsuiteContextRefineNode:
    SYS_PROMPT = """
You are a refinement assistant focused on finding a single quick verification command from README/docs.

Decision policy:
- If a suitable command has already been identified, do NOT request more context (return empty refined_query).
- If not, propose a short refined query that targets README, Quickstart, Installation, Getting Started, or Makefile targets referenced in docs to surface a quick, safe command.
- Avoid asking for code internals; prioritize documentation text and examples.

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

Recent commands:
--- BEGIN COMMANDS ---
{commands_str}
--- END DOC ---

Goal: If no quick verification command has been identified yet, craft a concise follow-up instruction that will search README, Quickstart, Installation, Getting Started sections, or Makefile targets referenced in docs to find a minimal, safe command (version/help/make check/pytest -q).
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
        # doc_snippets = transform_tool_messages_to_str(
        #     extract_last_tool_messages(state.get("testsuite_context_command", []))
        # )
        # return self.REFINE_PROMPT.format(
        #     file_tree=self.file_tree,
        #     original_query=original_query,
        #     doc_snippets=doc_snippets,
        # )
        commands = state.get("testsuite_command", [])
        commands_str = "\n".join([c for c in commands if c])
        return self.REFINE_PROMPT.format(
            file_tree=self.file_tree,
            original_query=original_query,
            commands_str=commands_str,
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

        return state_update
