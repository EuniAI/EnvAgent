import json
import logging
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

import click
from datasets import load_dataset
from tqdm import tqdm

from app.configuration.config import settings
from app.container.general_container import GeneralContainer
from app.container.user_defined_container import UserDefinedContainer
from app.lang_graph.subgraphs.bug_reproduction_subgraph import BugReproductionSubgraph
from app.services.knowledge_graph_service import KnowledgeGraphService
from app.services.llm_service import LLMService
from app.services.neo4j_service import Neo4jService
from app.services.repository_service import RepositoryService

SWEBENCH_IMAGE_FORMAT = "swebench/sweb.eval.x86_64.{repo_prefix}_1776_{instance_id}:v1"

GITHUB_HTTPS_URL = "https://github.com/{repo_name}.git"

LOG_DIR = Path(settings.WORKING_DIRECTORY) / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Initialize services with configuration settings
neo4j_service = Neo4jService(
    settings.NEO4J_URI,
    settings.NEO4J_USERNAME,
    settings.NEO4J_PASSWORD,
)

knowledge_graph_service = KnowledgeGraphService(
    neo4j_service,
    settings.NEO4J_BATCH_SIZE,
    settings.KNOWLEDGE_GRAPH_MAX_AST_DEPTH,
    settings.KNOWLEDGE_GRAPH_CHUNK_SIZE,
    settings.KNOWLEDGE_GRAPH_CHUNK_OVERLAP,
)

repository_service = RepositoryService(
    kg_service=knowledge_graph_service, working_dir=settings.WORKING_DIRECTORY
)

llm_service = LLMService(
    advanced_model_name=settings.ADVANCED_MODEL,
    base_model_name=settings.BASE_MODEL,
    openai_format_api_key=settings.OPENAI_FORMAT_API_KEY,
    openai_format_base_url=settings.OPENAI_FORMAT_BASE_URL,
    anthropic_api_key=settings.ANTHROPIC_API_KEY,
    gemini_api_key=settings.GEMINI_API_KEY,
    temperature=settings.TEMPERATURE,
    max_output_tokens=settings.MAX_OUTPUT_TOKENS,
)


def reproduce_bug(
    issue_title: str,
    issue_body: str,
    issue_comments: Sequence[Mapping[str, str]],
    github_url: str,
    github_token: str,
    commit_id: str = None,
    dockerfile_content: str = None,
    image_name: str = None,
    build_commands: Sequence[str] = None,
    test_commands: Sequence[str] = None,
    workdir: str = None,
) -> tuple[bool, None, None, None] | tuple[bool, str, str, str]:
    # Set up a dedicated logger for this thread
    logger = logging.getLogger(f"thread-{threading.get_ident()}.prometheus")
    logger.setLevel(getattr(logging, settings.LOGGING_LEVEL))
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"{timestamp}_{threading.get_ident()}.log"
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if dockerfile_content or image_name:
        if workdir is None:
            raise Exception("workdir must be provided for user defined environment")
    # Clone the repository
    print("Starting cloning the repository...")
    repo_path = repository_service.clone_github_repo(github_token, github_url, commit_id)
    print(f"Repository cloned to: {repo_path}")

    # Build and save the knowledge graph
    root_node_id = knowledge_graph_service.build_and_save_knowledge_graph(repo_path)
    print(f"Knowledge graph created with root node ID: {root_node_id}")
    knowledge_graph = knowledge_graph_service.get_knowledge_graph(
        root_node_id,
        settings.KNOWLEDGE_GRAPH_MAX_AST_DEPTH,
        settings.KNOWLEDGE_GRAPH_CHUNK_SIZE,
        settings.KNOWLEDGE_GRAPH_CHUNK_OVERLAP,
    )
    git_repo = repository_service.get_repository(repo_path)

    # Construct the working directory
    if dockerfile_content or image_name:
        container = UserDefinedContainer(
            repo_path,
            workdir,
            build_commands,
            test_commands,
            dockerfile_content,
            image_name,
        )
    else:
        container = GeneralContainer(repo_path)
    # Start the container
    container.build_docker_image()
    container.start_container()

    # Initialize the bug reproduce graph
    bug_reproduction_subgraph = BugReproductionSubgraph(
        advanced_model=llm_service.advanced_model,
        base_model=llm_service.base_model,
        container=container,
        kg=knowledge_graph,
        git_repo=git_repo,
        neo4j_driver=neo4j_service.neo4j_driver,
        max_token_per_neo4j_result=settings.MAX_TOKEN_PER_NEO4J_RESULT,
    )

    # Invoke the bug reproduction subgraph
    print("Starting bug reproduction...")
    try:
        output_states = bug_reproduction_subgraph.invoke(
            issue_title=issue_title, issue_body=issue_body, issue_comments=issue_comments
        )
    except Exception as e:
        logger.error(f"Error in answer_issue: {str(e)}\n{traceback.format_exc()}")
        return False, None, None, None
    finally:
        # Clean up resources
        container.cleanup()
        git_repo.reset_repository()
        logger.removeHandler(file_handler)
        file_handler.close()
    # Clear the knowledge graph from Neo4j after use
    knowledge_graph_service.clear_kg(knowledge_graph.root_node_id)
    # Clear the repository from the repository service
    repo_path.rmdir()
    
    print(f"reproduced_bug: {output_states['reproduced_bug']}")
    print(f"reproduced_bug_file: {output_states['reproduced_bug_file']}")
    print(f"reproduced_bug_commands: {output_states['reproduced_bug_commands']}")
    print(f"reproduced_bug_patch: {output_states['reproduced_bug_patch']}")
    return (
        output_states["reproduced_bug"],
        output_states["reproduced_bug_file"],
        output_states["reproduced_bug_commands"],
        output_states["reproduced_bug_patch"],
    )


@click.command()
@click.option(
    "--dataset_name",
    "-d",
    required=True,
    help="Name of the SWE bench dataset generate patches",
)
@click.option(
    "--github_token",
    "-g",
    help="Github token to access private repositories",
    default=None,
)
@click.option(
    "--file",
    "-f",
    help="File to save the predictions or continue patch generating.",
    default=f"predictions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
)
def main(
    dataset_name: str,
    github_token: str,
    file: str,
):
    dataset = load_dataset(dataset_name)
    filtered_dataset = dataset["test"]
    print(f"Dataset loaded: {dataset_name}")
    predictions = {}

    for github_issue in tqdm(filtered_dataset):
        # Get Issue information
        repo_prefix = github_issue["repo"].split("/")[0]
        instance_id = github_issue["instance_id"].split("__")[-1]
        image_name = SWEBENCH_IMAGE_FORMAT.format(repo_prefix=repo_prefix, instance_id=instance_id)
        github_url = GITHUB_HTTPS_URL.format(repo_name=github_issue["repo"])
        commit_id = github_issue["base_commit"]
        problem_statement_lines = github_issue["problem_statement"].splitlines()
        issue_title = problem_statement_lines[0]
        issue_body = "\n".join(problem_statement_lines[1:])

        # Reproduce the bug
        (reproduced_bug, reproduced_bug_file, reproduced_bug_commands, reproduced_bug_patch) = (
            reproduce_bug(
                issue_title,
                issue_body,
                [],
                github_url,
                github_token,
                commit_id,
                None,
                image_name,
                None,
                None,
                "/testbed",
            )
        )
        predictions[github_issue["instance_id"]] = {
            "reproduced_bug": reproduced_bug,
            "reproduced_bug_file": str(reproduced_bug_file),
            "reproduced_bug_commands": reproduced_bug_commands,
            "reproduced_bug_patch": reproduced_bug_patch,
        }

        with open(file, "w", encoding="utf-8") as f:
            json.dump(predictions, f, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    try:
        main()
    finally:
        # Close the Neo4j service connection
        neo4j_service.close()
