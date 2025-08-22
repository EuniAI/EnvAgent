"""Service for managing repository (GitHub or local) operations."""

import uuid
from pathlib import Path
from typing import Optional

from app.git_manage.git_repository import GitRepository
from app.services.base_service import BaseService
from app.services.knowledge_graph_service import KnowledgeGraphService


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
