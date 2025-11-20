
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.states.context_retrieval_state import ContextRetrievalState
from app.lang_graph.states.env_implement_state import save_env_implement_states_to_json
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

Files Already Searched (已搜索的文件):
The following files have already been searched in previous iterations. DO NOT request these files again:
--- BEGIN INVOLVED FILES ---
{involved_files}
--- END INVOLVED FILES ---

Analyze if the current context is sufficient to generate a complete Dockerfile by considering:
1. Do you have access to all necessary dependency files (requirements.txt, package.json, pom.xml, etc.)?
2. Are build configuration files visible (Makefile, CMakeLists.txt, build.gradle, etc.)?
3. Do you have environment configuration files (.env, config files, application.properties, etc.)?
4. Is there setup documentation available (README.md, INSTALL.md, SETUP.md)?
5. Are there existing Docker-related files (Dockerfile, docker-compose.yml, etc.)?
6. Do you understand the project's runtime requirements and system dependencies?

CRITICAL: When deciding whether to request additional context:
- DO NOT request files that are already in the "Files Already Searched" list above
- If a file you need is in the involved_files list, it means it has already been searched
- Only request NEW files that have NOT been searched yet
- If many files have been searched without finding critical dependencies, consider stopping the search

Only request additional context if essential information is missing for Dockerfile generation. Ensure you're not requesting:
- Information already provided in previous queries
- Nice-to-have but non-essential details
- Files that aren't critical for basic Dockerfile generation
- Files that are already in the involved_files list

If additional context is needed:
- Be specific about what configuration files you're looking for
- Focus on dependency management, build systems, and environment setup
- Consider both configuration files and documentation that might be relevant
- Make sure the files you request are NOT in the involved_files list
"""

    def __init__(self, model: BaseChatModel, kg: KnowledgeGraph, local_path: str):
        self.file_tree = kg.get_file_tree()
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.SYS_PROMPT),
                ("human", "{human_prompt}"),
            ]
        )
        structured_llm = model.with_structured_output(FileContextRefineStructuredOutput)
        self.model = prompt | structured_llm
        self.local_path = local_path    
        self._logger, file_handler = get_thread_logger(__name__)

    def format_refine_message(self, state: ContextRetrievalState):
        original_query = state["query"]
        context = "\n\n".join([str(context) for context in state["context"]])
        
        # Get involved_files from state
        involved_files = state.get("involved_files", [])
        # if not isinstance(involved_files, list):
        #     involved_files = list(involved_files) if involved_files else []
        
        # Format involved_files list for the prompt
        if involved_files:
            involved_files_str = "\n".join([f"  - {file}" for file in involved_files])
        else:
            involved_files_str = "  (No files have been searched yet)"
        
        return self.REFINE_PROMPT.format(
            file_tree=self.file_tree,
            original_query=original_query,
            context=context,
            involved_files=involved_files_str,
        )

    def filter_query_for_not_found_files(
        self, refined_query: str, not_found_files: list[str]
    ) -> str:
        """
        Filter out references to files that are known to be not found from the refined query.
        
        Args:
            refined_query: The original refined query
            not_found_files: List of files known to be not found
            
        Returns:
            Filtered refined query, or empty string if all requested files are not found
        """
        if not refined_query or not not_found_files:
            return refined_query
        
        query_lower = refined_query.lower()
        filtered_query = refined_query
        
        # Check if the query mentions any not found files
        mentions_not_found = False
        for file_name in not_found_files:
            file_lower = file_name.lower()
            # Check if the file name appears in the query
            if file_lower in query_lower:
                mentions_not_found = True
                self._logger.info(
                    f"Filtering out reference to not found file: {file_name}"
                )
                # Remove the file name from the query (simple approach)
                # This is a basic implementation - could be improved with more sophisticated NLP
                filtered_query = filtered_query.replace(file_name, "")
                filtered_query = filtered_query.replace(file_lower, "")
                # Also remove common variations
                filtered_query = filtered_query.replace(file_name.replace(".", ""), "")
        
        # Clean up extra spaces
        filtered_query = " ".join(filtered_query.split())
        
        # If the query becomes too short or only mentions not found files, return empty
        if len(filtered_query.strip()) < 10:
            self._logger.info(
                "Refined query filtered to empty after removing not found files"
            )
            return ""
        
        return filtered_query

    def __call__(self, state: ContextRetrievalState):
        # Get existing not_found_files and involved_files from state
        existing_involved_files = state.get("involved_files", [])
        if not isinstance(existing_involved_files, list):
            existing_involved_files = list(existing_involved_files) if existing_involved_files else []
        
        if "max_refined_query_loop" in state and state["max_refined_query_loop"] == 0:
            self._logger.info("Reached max_refined_query_loop, not asking for more context")
            return {
                "refined_query": "", 
                "involved_files": existing_involved_files,
            }

        # Check if we have any context at all - if not, we should stop after a few attempts
        current_context = state.get("context", [])
        if len(current_context) == 0 and state.get("max_refined_query_loop", 0) < 2:
            self._logger.info("No context found after multiple attempts, stopping search")
            return {
                "refined_query": "", 
                "involved_files": existing_involved_files,
            }
        
        # # Early exit: if we have many involved files but little context, be more conservative
        # if len(existing_involved_files) > 10 and len(current_context) < 3:
        #     self._logger.info(
        #         f"Too many files searched ({len(existing_involved_files)}) with little context found, "
        #         "stopping to avoid infinite loop"
        #     )
        #     return {
        #         "refined_query": "", 
        #         "involved_files": existing_involved_files,
        #     }

        human_prompt = self.format_refine_message(state)
        self._logger.debug(human_prompt)
        response = self.model.invoke({"human_prompt": human_prompt})
        self._logger.debug(response)

        # Filter refined query to remove references to not found files and involved files
        filtered_refined_query = self.filter_query_for_not_found_files(
            response.refined_query, existing_involved_files
        )
        
        # # Also filter out references to involved_files
        # filtered_refined_query = self.filter_query_for_not_found_files(filtered_refined_query, existing_involved_files)

        state_update = {
            "refined_query": filtered_refined_query,
            "involved_files": existing_involved_files,
        }

        if "max_refined_query_loop" in state:
            state_update["max_refined_query_loop"] = state["max_refined_query_loop"] - 1

        # # Additional stop condition: if the refined query is similar to previous queries, stop
        # if filtered_refined_query:
        #     # Check for repetitive patterns in the refined query
        #     query_lower = filtered_refined_query.lower()

        #     # Check if query mentions files that are already known to be not found or involved
        #     mentions_involved = any(
        #         file_name.lower() in query_lower for file_name in existing_involved_files
        #     )
            

        #     state_update["context_provider_messages"] = [
        #         HumanMessage(content=filtered_refined_query)
        #     ]

        save_env_implement_states_to_json(state, self.local_path)
        return state_update
