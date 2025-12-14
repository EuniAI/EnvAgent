from typing import Dict, Sequence

import neo4j
from langchain_core.language_models.chat_models import BaseChatModel

from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.env_nodes.env_implement_file_context_retrieval_subgraph import EnvImplementFileContextRetrievalSubgraph
from app.models.context import Context
from app.utils.logger_manager import get_thread_logger

from app.lang_graph.states.env_implement_state import save_env_implement_states_to_json

class EnvImplementFileContextRetrievalSubgraphNode:
    def __init__(
        self,
        model: BaseChatModel,
        kg: KnowledgeGraph,
        local_path: str,
        neo4j_driver: neo4j.Driver,
        max_token_per_neo4j_result: int,
        query_key_name: str,
        context_key_name: str,
    ):
        self._logger, _file_handler = get_thread_logger(__name__)
        self.env_implement_file_context_retrieval_subgraph = EnvImplementFileContextRetrievalSubgraph(
            model=model,
            kg=kg,
            local_path=local_path,
            neo4j_driver=neo4j_driver,
            max_token_per_neo4j_result=max_token_per_neo4j_result,
        )
        self.query_key_name = "env_implement_file_context_query"
        self.context_key_name = "env_implement_file_context"
        self.local_path = local_path
    def __call__(self, state: Dict) -> Dict[str, Sequence[Context]]:
        self._logger.info("Enter context retrieval subgraph")
        output_state = self.env_implement_file_context_retrieval_subgraph.invoke(
            state[self.query_key_name], state["max_refined_query_loop"]
        )
        self._logger.info(f"Context retrieved: {output_state['context']}")
        state_update = {self.context_key_name: output_state["context"]}
        state.update(state_update)
        save_env_implement_states_to_json(state, self.local_path)
        return state_update
