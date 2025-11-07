#!/usr/bin/env python3
"""
Repository Management Tool

This script provides a command-line interface to manage repositories in the database.
You can list, view details, and delete repositories.
"""

import json
from pathlib import Path
from typing import Optional

import click

from app.configuration.config import settings
from app.services.knowledge_graph_service import KnowledgeGraphService
from app.services.neo4j_service import Neo4jService
from app.services.repository_service import RepositoryService


def init_services():
    """Initialize the required services."""
    neo4j_service = Neo4jService(
        settings.NEO4J_URI,
        settings.NEO4J_USERNAME,
        settings.NEO4J_PASSWORD,
    )

    knowledge_graph_service = KnowledgeGraphService(
        neo4j_service,
        settings.NEO4J_BATCH_SIZE,
        settings.KNOWLEDGE_GRAPH_ASTNODE_ARGS,
        settings.KNOWLEDGE_GRAPH_CHUNK_SIZE,
        settings.KNOWLEDGE_GRAPH_CHUNK_OVERLAP,
    )

    repository_service = RepositoryService(
        kg_service=knowledge_graph_service, working_dir=settings.WORKING_DIRECTORY
    )

    return repository_service, neo4j_service


@click.group()
def cli():
    """Repository Management Tool for Prometheus Bug Reproduction Agent."""
    pass


@cli.command()
def list():
    """List all repositories in the database."""
    repository_service, neo4j_service = init_services()

    try:
        repositories = repository_service.list_repositories()

        if not repositories:
            click.echo("📭 No repositories found in the database.")
            return

        click.echo(f"📚 Found {len(repositories)} repositories:\n")
        click.echo("=" * 80)

        for i, repo in enumerate(repositories, 1):
            click.echo(f"{i}. URL: {repo.url}")
            click.echo(f"   Commit ID: {repo.commit_id or 'Latest'}")
            click.echo(f"   Path: {repo.playground_path}")
            click.echo(f"   KG Root Node ID: {repo.kg_root_node_id}")

            # Check if path still exists
            path_exists = Path(repo.playground_path).exists()
            status = "✅ Exists" if path_exists else "❌ Missing"
            click.echo(f"   Status: {status}")
            click.echo("-" * 80)

    except Exception as e:
        click.echo(f"❌ Error listing repositories: {e}")
    finally:
        neo4j_service.close()


@cli.command()
@click.argument("url")
@click.option("--commit-id", "-c", help="Specific commit ID (optional)")
def info(url: str, commit_id: Optional[str]):
    """Show detailed information about a specific repository."""
    repository_service, neo4j_service = init_services()

    try:
        repository = repository_service.repository_storage.get_repository_by_url_and_commit_id(
            url, commit_id
        )

        if not repository:
            click.echo(f"❌ Repository not found: {url} (commit: {commit_id or 'Latest'})")
            return

        click.echo("📋 Repository Information:")
        click.echo("=" * 50)
        click.echo(f"URL: {repository.url}")
        click.echo(f"Commit ID: {repository.commit_id or 'Latest'}")
        click.echo(f"Local Path: {repository.playground_path}")
        click.echo(f"KG Root Node ID: {repository.kg_root_node_id}")
        click.echo(f"KG Max AST Depth: {repository.kg_max_ast_depth}")
        click.echo(f"KG Chunk Size: {repository.kg_chunk_size}")
        click.echo(f"KG Chunk Overlap: {repository.kg_chunk_overlap}")

        # Check path status
        path = Path(repository.playground_path)
        if path.exists():
            click.echo("Path Status: ✅ Exists")
            # Show directory size
            total_size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            size_mb = total_size / (1024 * 1024)
            click.echo(f"Directory Size: {size_mb:.2f} MB")
        else:
            click.echo("Path Status: ❌ Missing")

        # Check if knowledge graph exists in Neo4j
        try:
            kg_exists = repository_service.kg_service.kg_handler.knowledge_graph_exists(
                repository.kg_root_node_id
            )
            kg_status = "✅ Exists" if kg_exists else "❌ Missing"
            click.echo(f"Knowledge Graph: {kg_status}")
        except Exception as e:
            click.echo(f"Knowledge Graph: ❓ Error checking ({e})")

    except Exception as e:
        click.echo(f"❌ Error getting repository info: {e}")
    finally:
        neo4j_service.close()


@cli.command()
@click.argument("url")
@click.option("--commit-id", "-c", help="Specific commit ID (optional)")
@click.option("--force", "-f", is_flag=True, help="Force deletion without confirmation")
def delete(url: str, commit_id: Optional[str], force: bool):
    """Delete a specific repository from the database."""
    repository_service, neo4j_service = init_services()

    try:
        # Check if repository exists
        repository = repository_service.repository_storage.get_repository_by_url_and_commit_id(
            url, commit_id
        )

        if not repository:
            click.echo(f"❌ Repository not found: {url} (commit: {commit_id or 'Latest'})")
            return

        # Show repository info
        click.echo("📋 Repository to delete:")
        click.echo(f"   URL: {repository.url}")
        click.echo(f"   Commit ID: {repository.commit_id or 'Latest'}")
        click.echo(f"   Path: {repository.playground_path}")
        click.echo(f"   KG Root Node ID: {repository.kg_root_node_id}")

        # Confirmation
        if not force:
            if not click.confirm(
                "\n⚠️  Are you sure you want to delete this repository? This will remove:\n"
                "   - Local repository files\n"
                "   - Knowledge graph from Neo4j\n"
                "   - Repository metadata\n"
                "\nContinue?"
            ):
                click.echo("❌ Deletion cancelled.")
                return

        # Delete repository
        click.echo("\n🗑️  Deleting repository...")
        success = repository_service.delete_repository(url, commit_id)

        if success:
            click.echo("✅ Repository deleted successfully!")
        else:
            click.echo("❌ Failed to delete repository.")

    except Exception as e:
        click.echo(f"❌ Error deleting repository: {e}")
    finally:
        neo4j_service.close()


@cli.command()
@click.argument("url")
def delete_all_commits(url: str):
    """Delete all commits/versions of a repository."""
    repository_service, neo4j_service = init_services()

    try:
        # Find all repositories with this URL
        repositories = repository_service.find_repositories_by_url(url)

        if not repositories:
            click.echo(f"❌ No repositories found for URL: {url}")
            return

        click.echo(f"📋 Found {len(repositories)} versions of {url}:")
        for repo in repositories:
            click.echo(f"   - Commit: {repo.commit_id or 'Latest'}")

        # Confirmation
        if not click.confirm(
            f"\n⚠️  Are you sure you want to delete ALL {len(repositories)} versions? This will remove:\n"
            "   - All local repository files\n"
            "   - All knowledge graphs from Neo4j\n"
            "   - All repository metadata\n"
            "\nContinue?"
        ):
            click.echo("❌ Deletion cancelled.")
            return

        # Delete all versions
        click.echo(f"\n🗑️  Deleting {len(repositories)} repositories...")
        deleted_count = 0

        for repo in repositories:
            success = repository_service.delete_repository(repo.url, repo.commit_id)
            if success:
                deleted_count += 1
                click.echo(f"   ✅ Deleted: {repo.commit_id or 'Latest'}")
            else:
                click.echo(f"   ❌ Failed: {repo.commit_id or 'Latest'}")

        click.echo(f"\n✅ Successfully deleted {deleted_count}/{len(repositories)} repositories!")

    except Exception as e:
        click.echo(f"❌ Error deleting repositories: {e}")
    finally:
        neo4j_service.close()


@cli.command()
@click.option(
    "--format", "-f", type=click.Choice(["table", "json"]), default="table", help="Output format"
)
def export(format: str):
    """Export repository metadata."""
    repository_service, neo4j_service = init_services()

    try:
        repositories = repository_service.list_repositories()

        if format == "json":
            data = [repo.to_dict() for repo in repositories]
            click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            # Table format
            if not repositories:
                click.echo("📭 No repositories found.")
                return

            click.echo(f"📊 Repository Database Export ({len(repositories)} entries):")
            click.echo("=" * 120)
            click.echo(f"{'#':<3} {'URL':<40} {'Commit':<15} {'KG ID':<8} {'Status':<10}")
            click.echo("-" * 120)

            for i, repo in enumerate(repositories, 1):
                commit_short = (
                    (repo.commit_id[:12] + "...")
                    if repo.commit_id and len(repo.commit_id) > 15
                    else (repo.commit_id or "Latest")
                )
                url_short = repo.url[:37] + "..." if len(repo.url) > 40 else repo.url
                path_exists = Path(repo.playground_path).exists()
                status = "✅ OK" if path_exists else "❌ Missing"

                click.echo(
                    f"{i:<3} {url_short:<40} {commit_short:<15} {repo.kg_root_node_id:<8} {status:<10}"
                )

    except Exception as e:
        click.echo(f"❌ Error exporting repositories: {e}")
    finally:
        neo4j_service.close()


if __name__ == "__main__":
    cli()
