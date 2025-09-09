"""Repository model for storing repository metadata."""

from dataclasses import dataclass
from typing import Optional
import json
from pathlib import Path


@dataclass
class Repository:
    """Repository model to track cloned repositories and their knowledge graph state."""
    
    url: str
    commit_id: Optional[str]
    playground_path: str
    kg_root_node_id: int
    kg_max_ast_depth: int
    kg_chunk_size: int
    kg_chunk_overlap: int
    
    def to_dict(self) -> dict:
        """Convert repository to dictionary for JSON serialization."""
        return {
            "url": self.url,
            "commit_id": self.commit_id,
            "playground_path": self.playground_path,
            "kg_root_node_id": self.kg_root_node_id,
            "kg_max_ast_depth": self.kg_max_ast_depth,
            "kg_chunk_size": self.kg_chunk_size,
            "kg_chunk_overlap": self.kg_chunk_overlap,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Repository":
        """Create repository from dictionary."""
        return cls(
            url=data["url"],
            commit_id=data["commit_id"],
            playground_path=data["playground_path"],
            kg_root_node_id=data["kg_root_node_id"],
            kg_max_ast_depth=data["kg_max_ast_depth"],
            kg_chunk_size=data["kg_chunk_size"],
            kg_chunk_overlap=data["kg_chunk_overlap"],
        )


class RepositoryStorage:
    """Simple file-based storage for repository metadata."""
    
    def __init__(self, storage_path: Path):
        """Initialize repository storage.
        
        Args:
            storage_path: Path to the JSON file for storing repository data.
        """
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize empty storage if file doesn't exist
        if not self.storage_path.exists():
            self._save_repositories([])
    
    def _load_repositories(self) -> list[Repository]:
        """Load all repositories from storage."""
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [Repository.from_dict(repo_data) for repo_data in data]
        except (json.JSONDecodeError, FileNotFoundError, KeyError):
            return []
    
    def _save_repositories(self, repositories: list[Repository]):
        """Save all repositories to storage."""
        data = [repo.to_dict() for repo in repositories]
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def get_repository_by_url_and_commit_id(self, url: str, commit_id: Optional[str]) -> Optional[Repository]:
        """Get repository by URL and commit ID.
        
        Args:
            url: Repository URL
            commit_id: Commit ID (can be None)
            
        Returns:
            Repository if found, None otherwise
        """
        repositories = self._load_repositories()
        for repo in repositories:
            if repo.url == url and repo.commit_id == commit_id:
                return repo
        return None
    
    def save_repository(self, repository: Repository) -> Repository:
        """Save a repository to storage.
        
        Args:
            repository: Repository to save
            
        Returns:
            The saved repository
        """
        repositories = self._load_repositories()
        
        # Check if repository already exists and update it
        for i, existing_repo in enumerate(repositories):
            if existing_repo.url == repository.url and existing_repo.commit_id == repository.commit_id:
                repositories[i] = repository
                self._save_repositories(repositories)
                return repository
        
        # Add new repository
        repositories.append(repository)
        self._save_repositories(repositories)
        return repository
    
    def delete_repository(self, url: str, commit_id: Optional[str]) -> bool:
        """Delete repository from storage.
        
        Args:
            url: Repository URL
            commit_id: Commit ID
            
        Returns:
            True if repository was deleted, False if not found
        """
        repositories = self._load_repositories()
        for i, repo in enumerate(repositories):
            if repo.url == url and repo.commit_id == commit_id:
                del repositories[i]
                self._save_repositories(repositories)
                return True
        return False
