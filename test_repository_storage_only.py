#!/usr/bin/env python3
"""
Simplified test script to verify only the repository storage logic works correctly.
This avoids complex dependencies and focuses on the core repository-based functionality.
"""

import json
import tempfile
from pathlib import Path

from app.models.repository import Repository, RepositoryStorage


def test_repository_storage():
    """Test the repository storage functionality."""
    print("Testing RepositoryStorage...")

    with tempfile.TemporaryDirectory() as temp_dir:
        storage_path = Path(temp_dir) / "test_repos.json"
        storage = RepositoryStorage(storage_path)

        # Test saving and retrieving repository
        repo = Repository(
            url="https://github.com/test/repo.git",
            commit_id="abc123",
            playground_path="/tmp/test",
            kg_root_node_id=1,
            kg_max_ast_depth=3,
            kg_chunk_size=1000,
            kg_chunk_overlap=200,
        )

        # Save repository
        saved_repo = storage.save_repository(repo)
        print(f"✓ Saved repository: {saved_repo.url}")

        # Verify the JSON file was created and has correct content
        assert storage_path.exists()
        with open(storage_path, "r") as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["url"] == repo.url
            assert data[0]["commit_id"] == repo.commit_id
            assert data[0]["kg_root_node_id"] == repo.kg_root_node_id
        print("✓ JSON storage file created with correct data")

        # Retrieve repository
        retrieved_repo = storage.get_repository_by_url_and_commit_id(
            "https://github.com/test/repo.git", "abc123"
        )
        assert retrieved_repo is not None
        assert retrieved_repo.url == repo.url
        assert retrieved_repo.commit_id == repo.commit_id
        assert retrieved_repo.kg_root_node_id == repo.kg_root_node_id
        print("✓ Successfully retrieved repository")

        # Test non-existent repository
        non_existent = storage.get_repository_by_url_and_commit_id(
            "https://github.com/other/repo.git", "def456"
        )
        assert non_existent is None
        print("✓ Correctly returned None for non-existent repository")

        # Test saving another repository
        repo2 = Repository(
            url="https://github.com/test/repo.git",
            commit_id="def456",  # Different commit
            playground_path="/tmp/test2",
            kg_root_node_id=2,
            kg_max_ast_depth=3,
            kg_chunk_size=1000,
            kg_chunk_overlap=200,
        )
        storage.save_repository(repo2)

        # Verify we now have 2 repositories
        with open(storage_path, "r") as f:
            data = json.load(f)
            assert len(data) == 2
        print("✓ Successfully stored multiple repositories")

        # Test retrieving both
        repo1_retrieved = storage.get_repository_by_url_and_commit_id(
            "https://github.com/test/repo.git", "abc123"
        )
        repo2_retrieved = storage.get_repository_by_url_and_commit_id(
            "https://github.com/test/repo.git", "def456"
        )
        assert repo1_retrieved.kg_root_node_id == 1
        assert repo2_retrieved.kg_root_node_id == 2
        print("✓ Successfully retrieved different repositories by commit_id")

        # Test updating existing repository
        repo.kg_root_node_id = 99
        storage.save_repository(repo)

        updated_repo = storage.get_repository_by_url_and_commit_id(
            "https://github.com/test/repo.git", "abc123"
        )
        assert updated_repo.kg_root_node_id == 99

        # Should still have only 2 repositories (update, not add)
        with open(storage_path, "r") as f:
            data = json.load(f)
            assert len(data) == 2
        print("✓ Successfully updated existing repository")

        # Test deletion
        deleted = storage.delete_repository("https://github.com/test/repo.git", "abc123")
        assert deleted is True
        print("✓ Successfully deleted repository")

        # Verify deletion
        deleted_repo = storage.get_repository_by_url_and_commit_id(
            "https://github.com/test/repo.git", "abc123"
        )
        assert deleted_repo is None

        # Should now have only 1 repository
        with open(storage_path, "r") as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["commit_id"] == "def456"
        print("✓ Repository correctly removed after deletion")


def test_repository_with_none_commit_id():
    """Test repository storage with None commit_id (latest commit)."""
    print("\nTesting repository with None commit_id...")

    with tempfile.TemporaryDirectory() as temp_dir:
        storage_path = Path(temp_dir) / "test_repos.json"
        storage = RepositoryStorage(storage_path)

        # Test with None commit_id
        repo = Repository(
            url="https://github.com/test/repo.git",
            commit_id=None,  # Latest commit
            playground_path="/tmp/test",
            kg_root_node_id=1,
            kg_max_ast_depth=3,
            kg_chunk_size=1000,
            kg_chunk_overlap=200,
        )

        storage.save_repository(repo)

        # Retrieve with None commit_id
        retrieved_repo = storage.get_repository_by_url_and_commit_id(
            "https://github.com/test/repo.git", None
        )
        assert retrieved_repo is not None
        assert retrieved_repo.commit_id is None
        print("✓ Successfully handled None commit_id")

        # Test that different commit_id doesn't match
        different_commit_repo = storage.get_repository_by_url_and_commit_id(
            "https://github.com/test/repo.git", "abc123"
        )
        assert different_commit_repo is None
        print("✓ Correctly distinguished None vs specific commit_id")


def main():
    """Run all tests."""
    print("🧪 Testing Repository Storage Logic\n")
    print("=" * 60)

    try:
        test_repository_storage()
        test_repository_with_none_commit_id()

        print("\n" + "=" * 60)
        print("✅ All tests passed! Repository storage logic is working correctly.")
        print("\nKey features verified:")
        print("• Repository metadata storage and retrieval from JSON file")
        print("• Handling of different URL + commit_id combinations")
        print("• Support for None commit_id (latest commit)")
        print("• Repository updates and deletions")
        print("• Proper JSON serialization/deserialization")
        print("\n📋 Repository-based logic summary:")
        print("• Same URL + commit_id → Reuse existing repository")
        print("• Different URL or commit_id → Create new repository")
        print("• Persistent storage ensures data survives restarts")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
