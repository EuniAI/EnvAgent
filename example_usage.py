#!/usr/bin/env python3
"""
Example usage of the repository-based logic functionality.

This script demonstrates how to use the enhanced repository management features.
"""

from pathlib import Path
from app.models.repository import Repository, RepositoryStorage


def demonstrate_repository_management():
    """Demonstrate repository management functionality."""
    print("🚀 Repository-Based Logic Demo")
    print("=" * 50)
    
    # Initialize storage (in real usage, this would be in your working directory)
    storage_path = Path("example_repository_metadata.json")
    storage = RepositoryStorage(storage_path)
    
    print("📚 Repository Management Operations:\n")
    
    # 1. Add some example repositories
    print("1️⃣ Adding example repositories...")
    
    repos = [
        Repository(
            url="https://github.com/pytorch/pytorch.git",
            commit_id="v1.13.0",
            playground_path="/tmp/pytorch_v1.13.0",
            kg_root_node_id=100,
            kg_max_ast_depth=3,
            kg_chunk_size=1000,
            kg_chunk_overlap=200
        ),
        Repository(
            url="https://github.com/pytorch/pytorch.git",
            commit_id="v1.14.0",
            playground_path="/tmp/pytorch_v1.14.0",
            kg_root_node_id=101,
            kg_max_ast_depth=3,
            kg_chunk_size=1000,
            kg_chunk_overlap=200
        ),
        Repository(
            url="https://github.com/tensorflow/tensorflow.git",
            commit_id=None,  # Latest
            playground_path="/tmp/tensorflow_latest",
            kg_root_node_id=200,
            kg_max_ast_depth=3,
            kg_chunk_size=1000,
            kg_chunk_overlap=200
        ),
    ]
    
    for repo in repos:
        storage.save_repository(repo)
        commit_display = repo.commit_id or "Latest"
        print(f"   ✓ Added: {repo.url} ({commit_display})")
    
    # 2. List all repositories
    print(f"\n2️⃣ Listing all repositories...")
    all_repos = storage._load_repositories()
    print(f"   Found {len(all_repos)} repositories:")
    
    for i, repo in enumerate(all_repos, 1):
        commit_display = repo.commit_id or "Latest"
        print(f"   {i}. {repo.url} ({commit_display}) - KG ID: {repo.kg_root_node_id}")
    
    # 3. Find specific repository
    print(f"\n3️⃣ Finding specific repository...")
    specific_repo = storage.get_repository_by_url_and_commit_id(
        "https://github.com/pytorch/pytorch.git", "v1.13.0"
    )
    if specific_repo:
        print(f"   ✓ Found: {specific_repo.url} (v1.13.0) - KG ID: {specific_repo.kg_root_node_id}")
    
    # 4. Simulate repository-based logic
    print(f"\n4️⃣ Simulating repository-based logic...")
    
    def simulate_get_or_create(url: str, commit_id: str = None):
        """Simulate the get_or_create_repository logic."""
        existing = storage.get_repository_by_url_and_commit_id(url, commit_id)
        if existing:
            commit_display = commit_id or "Latest"
            print(f"   🔄 Reusing existing: {url} ({commit_display}) - KG ID: {existing.kg_root_node_id}")
            return existing.playground_path, existing.kg_root_node_id, False
        else:
            commit_display = commit_id or "Latest"
            print(f"   🆕 Would create new: {url} ({commit_display})")
            return f"/tmp/new_repo", 999, True
    
    # Test cases
    test_cases = [
        ("https://github.com/pytorch/pytorch.git", "v1.13.0"),  # Exists
        ("https://github.com/pytorch/pytorch.git", "v1.15.0"),  # New version
        ("https://github.com/tensorflow/tensorflow.git", None),  # Exists (Latest)
        ("https://github.com/huggingface/transformers.git", None),  # New repo
    ]
    
    for url, commit_id in test_cases:
        path, kg_id, is_new = simulate_get_or_create(url, commit_id)
    
    # 5. Delete repository
    print(f"\n5️⃣ Deleting repository...")
    deleted = storage.delete_repository("https://github.com/pytorch/pytorch.git", "v1.14.0")
    if deleted:
        print("   ✓ Successfully deleted PyTorch v1.14.0")
        
        # Show remaining repositories
        remaining = storage._load_repositories()
        print(f"   📊 Remaining repositories: {len(remaining)}")
        for repo in remaining:
            commit_display = repo.commit_id or "Latest"
            print(f"      - {repo.url} ({commit_display})")
    
    # 6. Show benefits
    print(f"\n6️⃣ Repository-based logic benefits:")
    print("   💾 Avoids re-cloning identical repositories")
    print("   🚀 Faster processing for repeated requests")
    print("   🧠 Reuses knowledge graphs from Neo4j")
    print("   💾 Saves disk space and bandwidth")
    print("   🔄 Consistent results for same repo versions")
    
    # Clean up example file
    if storage_path.exists():
        storage_path.unlink()
        print(f"\n🧹 Cleaned up example file: {storage_path}")


def show_command_examples():
    """Show command-line usage examples."""
    print(f"\n📋 Command-Line Usage Examples:")
    print("=" * 50)
    
    examples = [
        ("List all repositories", "python manage_repositories.py list"),
        ("Show repository details", "python manage_repositories.py info 'https://github.com/user/repo.git'"),
        ("Delete specific version", "python manage_repositories.py delete 'https://github.com/user/repo.git' -c abc123"),
        ("Delete all versions", "python manage_repositories.py delete-all-commits 'https://github.com/user/repo.git'"),
        ("Export as JSON", "python manage_repositories.py export --format json"),
        ("Export as table", "python manage_repositories.py export --format table"),
    ]
    
    for description, command in examples:
        print(f"📌 {description}:")
        print(f"   {command}\n")


def show_integration_example():
    """Show how to integrate with existing code."""
    print(f"🔧 Integration Example:")
    print("=" * 50)
    
    integration_code = '''
# Before (without repository-based logic):
def old_reproduce_bug(github_url, github_token, commit_id=None):
    # Always clone and build KG
    repo_path = repository_service.clone_github_repo(github_token, github_url, commit_id)
    kg_root_id = knowledge_graph_service.build_and_save_knowledge_graph(repo_path)
    # ... rest of processing
    
# After (with repository-based logic):
def new_reproduce_bug(github_url, github_token, commit_id=None):
    # Check for existing repo, reuse if available
    repo_path, kg_root_id, is_new = repository_service.get_or_create_repository(
        github_token, github_url, commit_id
    )
    
    if is_new:
        print("🆕 Created new repository")
    else:
        print("🔄 Reusing existing repository")
    
    # ... rest of processing (same as before)
    
    # Smart cleanup: only remove if new
    if is_new:
        repository_service.clean_repository(github_url, commit_id)
    else:
        print("🔄 Keeping repository for future use")
'''
    
    print(integration_code)


if __name__ == "__main__":
    demonstrate_repository_management()
    show_command_examples()
    show_integration_example()


