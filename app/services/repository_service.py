"""Service for managing repository (GitHub or local) operations."""

import shutil
import uuid
from pathlib import Path
from typing import Optional

from app.git_manage.git_repository import GitRepository
from app.models.repository import Repository, RepositoryStorage
from app.services.base_service import BaseService
from app.services.knowledge_graph_service import KnowledgeGraphService
from app.utils.logger_manager import get_thread_logger


class RepositoryService(BaseService):
    """Manages repository operations.

    This service provides functionality for Git repository operations including
    cloning repositories, managing commits, pushing changes, and maintaining
    a clean working directory. It integrates with a knowledge graph service
    to track repository state and avoid redundant operations.
    """

    def __init__(
        self,
        kg_service: KnowledgeGraphService,
        working_dir: str,
    ):
        """Initializes the repository service.

        Args:
          kg_service: Knowledge graph service instance for codebase tracking.
          working_dir: Base directory for repository operations. A 'repositories'
              subdirectory will be created under this path.
        """
        self.kg_service = kg_service
        self.target_directory = Path(working_dir) / "repositories"
        self.target_directory.mkdir(parents=True, exist_ok=True)

        # Initialize repository storage
        storage_path = Path(working_dir) / "repository_metadata.json"
        self.repository_storage = RepositoryStorage(storage_path)
        self.logger, file_handler = get_thread_logger(__name__)

    def get_new_playground_path(self) -> Path:
        """Generates a new unique playground path for cloning a repository.

        Returns:
            A Path object representing the new unique playground directory.
        """
        unique_id = uuid.uuid4().hex
        new_path = self.target_directory / unique_id
        while new_path.exists():
            unique_id = uuid.uuid4().hex
            new_path = self.target_directory / unique_id
        new_path.mkdir(parents=True)
        return new_path

    def clone_github_repo(
        self, github_token: str, https_url: str, commit_id: Optional[str] = None
    ) -> Path:
        """Clones a GitHub repository to the local workspace.

        Clones the specified repository and optionally checks out a specific commit.
        If the repository is already present and matches the requested state,
        the operation may be skipped.

        Args:
            github_token: GitHub access token for authentication.
            https_url: HTTPS URL of the GitHub repository.
            commit_id: Optional specific commit to check out.

        Returns:
            Path to the local repository directory.
        """
        git_repo = GitRepository()
        git_repo.from_clone_repository(https_url, github_token, self.get_new_playground_path())

        if commit_id:
            git_repo.checkout_commit(commit_id)
        return git_repo.get_working_directory()

    def get_repository(self, local_path: Path) -> GitRepository:
        git_repo = GitRepository()
        git_repo.from_local_repository(local_path)
        return git_repo

    def get_or_create_repository(
        self, github_token: str, https_url: str, commit_id: Optional[str] = None
    ) -> tuple[Path, int, bool]:
        """Get existing repository or create new one with knowledge graph.

        This method implements the repository-based logic:
        - If repository with same URL and commit_id exists, return existing path and KG root node ID
        - Otherwise, clone repository, build knowledge graph, and save metadata

        Args:
            github_token: GitHub access token for authentication.
            https_url: HTTPS URL of the GitHub repository.
            commit_id: Optional specific commit to check out.

        Returns:
            Tuple of (repository_path, kg_root_node_id, is_new_repository)
        """
        self.logger.info(f"Checking for existing repository: {https_url} (commit: {commit_id})")

        # Check if repository already exists
        existing_repo = self.repository_storage.get_repository_by_url_and_commit_id(
            https_url, commit_id
        )

        if existing_repo:
            repo_path = Path(existing_repo.playground_path)
            if repo_path.exists():
                self.logger.info(
                    f"Found existing repository at {repo_path} with KG root node ID: {existing_repo.kg_root_node_id}"
                )
                return repo_path, existing_repo.kg_root_node_id, False
            else:
                self.logger.warning(
                    f"Repository metadata exists but path {repo_path} not found. Removing stale metadata."
                )
                self.repository_storage.delete_repository(https_url, commit_id)

        # Repository doesn't exist or path is invalid, create new one
        self.logger.info(f"Creating new repository for {https_url} (commit: {commit_id})")

        # Clone repository
        repo_path = self.clone_github_repo(github_token, https_url, commit_id)

        # Build and save knowledge graph
        kg_root_node_id = self.kg_service.build_and_save_knowledge_graph(repo_path)

        # Save repository metadata
        repository = Repository(
            url=https_url,
            commit_id=commit_id,
            playground_path=str(repo_path),
            kg_root_node_id=kg_root_node_id,
            kg_max_ast_depth=self.kg_service.max_ast_depth,
            kg_chunk_size=self.kg_service.chunk_size,
            kg_chunk_overlap=self.kg_service.chunk_overlap,
        )
        self.repository_storage.save_repository(repository)

        self.logger.info(
            f"Successfully created repository at {repo_path} with KG root node ID: {kg_root_node_id}"
        )
        return repo_path, kg_root_node_id, True

    def clean_repository(self, https_url: str, commit_id: Optional[str] = None):
        """Clean up repository files and metadata.

        Args:
            https_url: Repository URL
            commit_id: Commit ID
        """
        repository = self.repository_storage.get_repository_by_url_and_commit_id(
            https_url, commit_id
        )
        if repository:
            repo_path = Path(repository.playground_path)
            if repo_path.exists():
                self.logger.info(f"Cleaning up repository at {repo_path}")
                shutil.rmtree(repo_path)

                # Also remove parent directory if it's empty
                try:
                    repo_path.parent.rmdir()
                except OSError:
                    # Directory not empty, that's fine
                    pass

            # Clean up knowledge graph
            self.kg_service.clear_kg(repository.kg_root_node_id)

            # Remove metadata
            self.repository_storage.delete_repository(https_url, commit_id)
            self.logger.info(
                f"Successfully cleaned up repository: {https_url} (commit: {commit_id})"
            )

    def delete_repository(self, https_url: str, commit_id: Optional[str] = None) -> bool:
        """Delete a specific repository from the database and filesystem.

        This method completely removes a repository including:
        - Local cloned files
        - Knowledge graph from Neo4j
        - Repository metadata

        Args:
            https_url: Repository URL
            commit_id: Commit ID (None for latest commit)

        Returns:
            True if repository was found and deleted, False if not found
        """
        self.logger.info(f"Attempting to delete repository: {https_url} (commit: {commit_id})")

        # Check if repository exists
        repository = self.repository_storage.get_repository_by_url_and_commit_id(
            https_url, commit_id
        )
        if not repository:
            self.logger.warning(f"Repository not found: {https_url} (commit: {commit_id})")
            return False

        # Clean up files
        repo_path = Path(repository.playground_path)
        if repo_path.exists():
            self.logger.info(f"Removing repository files at {repo_path}")
            shutil.rmtree(repo_path)

            # Also remove parent directory if it's empty
            try:
                repo_path.parent.rmdir()
                self.logger.info(f"Removed empty parent directory: {repo_path.parent}")
            except OSError:
                # Directory not empty, that's fine
                pass
        else:
            self.logger.warning(f"Repository path does not exist: {repo_path}")

        # Clean up knowledge graph from Neo4j
        try:
            self.kg_service.clear_kg(repository.kg_root_node_id)
            self.logger.info(
                f"Removed knowledge graph with root node ID: {repository.kg_root_node_id}"
            )
        except Exception as e:
            self.logger.error(f"Error removing knowledge graph: {e}")

        # Remove metadata
        deleted = self.repository_storage.delete_repository(https_url, commit_id)
        if deleted:
            self.logger.info(f"Successfully deleted repository: {https_url} (commit: {commit_id})")
        else:
            self.logger.error(
                f"Failed to delete repository metadata: {https_url} (commit: {commit_id})"
            )

        return deleted

    def list_repositories(self) -> list[Repository]:
        """List all repositories in the database.

        Returns:
            List of all Repository objects
        """
        return self.repository_storage._load_repositories()

    def find_repositories_by_url(self, https_url: str) -> list[Repository]:
        """Find all repositories with the given URL (different commits).

        Args:
            https_url: Repository URL to search for

        Returns:
            List of Repository objects with matching URL
        """
        all_repos = self.repository_storage._load_repositories()
        return [repo for repo in all_repos if repo.url == https_url]
