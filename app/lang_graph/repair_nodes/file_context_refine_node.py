
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.states.context_retrieval_state import ContextRetrievalState
from app.utils.logger_manager import get_thread_logger


class FileContextRefineStructuredOutput(BaseModel):
    reasoning: str = Field(description="Your step by step reasoning for Dockerfile generation.")
    refined_query: str = Field(
        "Additional query to ask the ContextRetriever if more environment configuration context is needed. Empty otherwise."
    )


class FileContextRefineNode:
    SYS_PROMPT = """\
You are an intelligent assistant specialized in analyzing environment configuration context to determine if
additional configuration files or documentation from the codebase is necessary to generate an accurate Dockerfile.

Your goal is to request additional context ONLY when necessary for Dockerfile generation:
1. When critical dependency files are missing (requirements.txt, package.json, pom.xml, etc.)
2. When build configuration files are not visible (Makefile, CMakeLists.txt, build.gradle, etc.)
3. When environment configuration files are needed (.env, config files, application.properties, etc.)
4. When setup documentation is missing (README.md, INSTALL.md, SETUP.md)
5. When existing Docker-related files are not included (Dockerfile, docker-compose.yml, etc.)
6. When runtime requirements and system dependencies are unclear

DO NOT request additional context if:
1. The current context already contains sufficient information to generate a complete Dockerfile
2. The additional context would only provide nice-to-have but non-essential details
3. The information is redundant with what's already available
4. The missing files are not critical for basic Dockerfile generation
5. You have already searched for the same types of files multiple times
6. The project appears to be a specific type (e.g., Java Maven project) and you have found the relevant build files

CRITICAL: If you have already searched for common dependency files (pom.xml, package.json, requirements.txt, etc.) 
and build files (Makefile, CMakeLists.txt, build.gradle, etc.) multiple times without finding them, 
DO NOT request them again. Instead, work with what you have or return an empty refined_query.

Provide your analysis in a structured format matching the ContextRefineStructuredOutput model.

Example output:
```json
{{
    "reasoning": "1. The current context includes package.json but lacks requirements.txt or other dependency files.\n2. No build configuration files (Makefile, CMakeLists.txt) are visible in the current context.\n3. Environment configuration files (.env, config files) are missing which could affect runtime setup.\n4. Therefore, additional context is needed to generate a complete and accurate Dockerfile.",
    "refined_query": "Please provide dependency management files (requirements.txt, package.json, pom.xml), build configuration files (Makefile, CMakeLists.txt), and environment configuration files (.env, config files) to ensure proper Dockerfile generation."
}}
```

PLEASE DO NOT INCLUDE ``` IN YOUR OUTPUT!
"""

    REFINE_PROMPT = """\
This is the codebase structure:
--- BEGIN FILE TREE ---
{file_tree}
--- END FILE TREE ---
    
This is the original user query:
--- BEGIN ORIGINAL QUERY ---
{original_query}
--- END ORIGINAL QUERY ---

All aggregated environment configuration context:
--- BEGIN AGGREGATED CONTEXT ---
{context}
--- END AGGREGATED CONTEXT ---

Analyze if the current context is sufficient to generate a complete Dockerfile by considering:
1. Do you have access to all necessary dependency files (requirements.txt, package.json, pom.xml, etc.)?
2. Are build configuration files visible (Makefile, CMakeLists.txt, build.gradle, etc.)?
3. Do you have environment configuration files (.env, config files, application.properties, etc.)?
4. Is there setup documentation available (README.md, INSTALL.md, SETUP.md)?
5. Are there existing Docker-related files (Dockerfile, docker-compose.yml, etc.)?
6. Do you understand the project's runtime requirements and system dependencies?

Only request additional context if essential information is missing for Dockerfile generation. Ensure you're not requesting:
- Information already provided in previous queries
- Nice-to-have but non-essential details
- Files that aren't critical for basic Dockerfile generation

If additional context is needed:
- Be specific about what configuration files you're looking for
- Focus on dependency management, build systems, and environment setup
- Consider both configuration files and documentation that might be relevant
"""

    def __init__(self, model: BaseChatModel, kg: KnowledgeGraph):
        self.file_tree = kg.get_file_tree()
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(FileContextRefineStructuredOutput)
        self.model = prompt | structured_llm
        self._logger, file_handler = get_thread_logger(__name__)

    def format_refine_message(self, state: ContextRetrievalState):
        original_query = state["query"]
        context = "\n\n".join([str(context) for context in state["context"]])
        return self.REFINE_PROMPT.format(
            file_tree=self.file_tree,
            original_query=original_query,
            context=context,
        )

    def __call__(self, state: ContextRetrievalState):
        if "max_refined_query_loop" in state and state["max_refined_query_loop"] == 0:
            self._logger.info("Reached max_refined_query_loop, not asking for more context")
            return {"refined_query": ""}

        # Check if we have any context at all - if not, we should stop after a few attempts
        current_context = state.get("context", [])
        if len(current_context) == 0 and state.get("max_refined_query_loop", 0) < 2:
            self._logger.info("No context found after multiple attempts, stopping search")
            return {"refined_query": ""}

        human_prompt = self.format_refine_message(state)
        self._logger.debug(human_prompt)
        response = self.model.invoke({"human_prompt": human_prompt})
        self._logger.debug(response)

        state_update = {"refined_query": response.refined_query}

        if "max_refined_query_loop" in state:
            state_update["max_refined_query_loop"] = state["max_refined_query_loop"] - 1

        # Additional stop condition: if the refined query is similar to previous queries, stop
        if response.refined_query:
            # Check if this is a repetitive query by looking at previous messages
            previous_messages = state.get("context_provider_messages", [])

            # Check for repetitive patterns in the refined query
            query_lower = response.refined_query.lower()
            repetitive_keywords = [
                "dockerfile",
                "pom.xml",
                "package.json",
                "requirements.txt",
                "makefile",
                "cmakelists.txt",
                "build.gradle",
                ".env",
                "config",
            ]

            # Count how many times we've searched for these common files
            search_count = 0
            for msg in previous_messages:
                if hasattr(msg, "content"):
                    msg_content = msg.content.lower()
                    for keyword in repetitive_keywords:
                        if keyword in msg_content:
                            search_count += 1

            # If we've searched for common files more than 3 times, stop
            if search_count > 3:
                self._logger.info(
                    f"Detected {search_count} repetitive file searches, stopping to avoid infinite loop"
                )
                return {"refined_query": ""}

            # If we've already made multiple queries and this one is asking for the same things, stop
            if len(previous_messages) > 2 and any(
                keyword in query_lower for keyword in repetitive_keywords
            ):
                self._logger.info(
                    "Detected repetitive file search queries, stopping to avoid infinite loop"
                )
                return {"refined_query": ""}

            state_update["context_provider_messages"] = [
                HumanMessage(content=response.refined_query)
            ]

        return state_update
