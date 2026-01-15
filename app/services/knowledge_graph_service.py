"""Service for managing and interacting with Knowledge Graphs in Neo4j."""

from pathlib import Path

from app.graph.knowledge_graph import KnowledgeGraph
from app.neo4j_manage import knowledge_graph_handler
from app.services.base_service import BaseService
from app.services.neo4j_service import Neo4jService
from app.utils.logger_manager import get_thread_logger


class KnowledgeGraphService(BaseService):
    """Manages the lifecycle and operations of Knowledge Graphs.

    This service handles the creation, persistence, and management of Knowledge Graphs
    that represent the whole codebase structures. It provides capabilities for building graphs
    from codebase, storing them in Neo4j, and managing their lifecycle.
    """

    def __init__(
        self,
        neo4j_service: Neo4jService,
        neo4j_batch_size: int,
        astnode_args: dict,
        chunk_size: int,
        chunk_overlap: int,
    ):
        """Initializes the Knowledge Graph service.

        Args:
          neo4j_service: Service providing Neo4j database access.
          neo4j_batch_size: Number of nodes to process in each Neo4j batch operation.
          astnode_args: Arguments for the ASTNode class.
          chunk_size: Chunk size for processing text files.
          chunk_overlap: Overlap size for processing text files.
        """
        self.kg_handler = knowledge_graph_handler.KnowledgeGraphHandler(
            neo4j_service.neo4j_driver, neo4j_batch_size
        )
        self.astnode_args = astnode_args
        self.max_ast_depth = astnode_args.max_ast_depth
        self.save_ast_depth = astnode_args.save_ast_depth
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._logger, _ = get_thread_logger(__name__)

    def build_and_save_knowledge_graph(self, path: Path) -> int:
        """Builds a new Knowledge Graph from source code and saves it to Neo4j.

        Creates a new Knowledge Graph representation of the codebase at the specified path,
        optionally associating it with a repository URL and commit. Any existing
        Knowledge Graph will be cleared before building the new one.

        Args:
            path: Path to the source code directory to analyze.
        Returns:
            The root node ID of the newly created Knowledge Graph.
        """
        from neo4j.exceptions import ConstraintError
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                root_node_id = self.kg_handler.get_new_knowledge_graph_root_node_id()
                kg = KnowledgeGraph(self.astnode_args, self.chunk_size, self.chunk_overlap, root_node_id)
                kg.build_graph(path)
                self.kg_handler.write_knowledge_graph(kg)
                return kg.root_node_id
            except ConstraintError as e:
                if attempt < max_retries - 1:
                    # If we hit a constraint error, the node_id might have been created
                    # by another process. Get a new one and retry.
                    self._logger.warning(
                        f"Constraint error while building knowledge graph (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying with a new node_id..."
                    )
                    continue
                else:
                    # Last attempt failed, raise the error
                    self._logger.error(
                        f"Failed to build knowledge graph after {max_retries} attempts due to constraint errors."
                    )
                    raise

    def clear_kg(self, root_node_id: int):
        self.kg_handler.clear_knowledge_graph(root_node_id)

    def knowledge_graph_exists(self, root_node_id: int) -> bool:
        """Check if a knowledge graph with the given root node ID exists in Neo4j.
        
        Args:
            root_node_id: The root node ID to check.
            
        Returns:
            True if the knowledge graph exists, False otherwise.
        """
        return self.kg_handler.knowledge_graph_exists(root_node_id)

    def get_knowledge_graph(
        self,
        root_node_id: int,
        chunk_size: int,
        chunk_overlap: int,
    ) -> KnowledgeGraph:
        return self.kg_handler.read_knowledge_graph(
            root_node_id, self.astnode_args, chunk_size, chunk_overlap
        )
