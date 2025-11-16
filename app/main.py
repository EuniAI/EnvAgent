import json
import os
import traceback
from datetime import datetime
from pathlib import PosixPath
from typing import Any, Dict, List

import click
from tqdm import tqdm

from app.configuration.config import settings
from app.container.general_container import GeneralContainer
from app.lang_graph.subgraphs.env_implement_subgraph import EnvImplementSubgraph
from app.lang_graph.subgraphs.env_repair_subgraph import EnvRepairSubgraph
from app.lang_graph.subgraphs.testsuite_subgraph import TestsuiteSubgraph
from app.services.knowledge_graph_service import KnowledgeGraphService
from app.services.llm_service import LLMService
from app.services.neo4j_service import Neo4jService
from app.services.repository_service import RepositoryService
from app.utils.logger_manager import get_thread_logger

# SWEBENCH_IMAGE_FORMAT = "swebench/sweb.eval.x86_64.{repo_prefix}_1776_{instance_id}:v1"

GITHUB_HTTPS_URL = "https://github.com/{repo_name}.git"

logger, file_handler = get_thread_logger(__name__)
debug_mode = True

test_mode = "pyright"  # generation pyright pytest


def serialize_states_for_json(states: Dict[str, Any]) -> Dict[str, Any]:
    """
    Serialize states dictionary to be JSON serializable.
    Handles special types like PosixPath, Context objects, etc.
    """
    serialized = {}
    for key, value in states.items():
        if isinstance(value, PosixPath):
            serialized[key] = str(value)
        elif isinstance(value, list):
            serialized[key] = []
            for item in value:
                if hasattr(item, "__dict__"):  # Handle objects with attributes
                    serialized[key].append(
                        {
                            "type": type(item).__name__,
                            "content": str(item) if hasattr(item, "content") else str(item),
                            "relative_path": getattr(item, "relative_path", None),
                            "start_line_number": getattr(item, "start_line_number", None),
                            "end_line_number": getattr(item, "end_line_number", None),
                        }
                    )
                else:
                    serialized[key].append(item)
        elif hasattr(value, "__dict__"):  # Handle objects with attributes
            serialized[key] = {
                "type": type(value).__name__,
                "content": str(value) if hasattr(value, "content") else str(value),
            }
        else:
            serialized[key] = value
    return serialized


def parse_all_projects_file(file_path: str) -> List[Dict[str, str]]:
    """
    解析 all_projects.txt 文件
    文件格式：项目名 仓库URL 编程语言 镜像名:标签
    Args:
        file_path: all_projects.txt 文件的路径
    Returns:
        包含项目信息的字典列表，每个字典包含：
        - name: 项目名称
        - repo_url: 仓库URL
        - language: 编程语言
        - image: 镜像名称
        - tag: 镜像标签
    """
    projects = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # 按空格分割，但URL可能包含空格，需要特殊处理
                parts = line.split()
                project_name = parts[0]
                repo_url = "http://github.com/" + project_name
                project_tag = parts[1]

                project_info = {
                    "name": project_name,
                    "repo_url": repo_url,
                    'tag': project_tag,
                }
                projects.append(project_info)

    except FileNotFoundError:
        logger.error(f"找不到文件 {file_path}")
        return []
    except Exception as e:
        logger.error(f"解析文件时发生错误: {e}")
        return []

    return projects


# Initialize services with configuration settings
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

llm_service = LLMService(
    advanced_model_name=settings.ADVANCED_MODEL,
    base_model_name=settings.BASE_MODEL,
    openai_format_api_key=settings.OPENAI_FORMAT_API_KEY,
    openai_format_base_url=settings.OPENAI_FORMAT_BASE_URL,
    anthropic_api_key=settings.ANTHROPIC_API_KEY,
    gemini_api_key=settings.GEMINI_API_KEY,
    vertex_ai_project_id=settings.VERTEX_AI_PROJECT_ID,
    vertex_ai_location=settings.VERTEX_AI_LOCATION,
    temperature=settings.TEMPERATURE,
)


def reproduce_test(
    github_url: str,
    github_token: str,
    project_tag: str,
    workdir: str = None,
) -> tuple[bool, None, None, None, None] | tuple[bool, Dict, Dict, str, str]:
    # if dockerfile_content or image_name:
    if workdir is None:
        raise Exception("workdir must be provided for user defined environment")
    # Get or create repository (repository-based logic)
    logger.info("Getting or creating repository...")
    repo_path, root_node_id, is_new_repository = repository_service.get_or_create_repository(
        github_token, github_url, project_tag
    )

    if is_new_repository:
        logger.info(f"New repository created at: {repo_path}")
    else:
        logger.info(f"Using existing repository at: {repo_path}")

    logger.info(f"Knowledge graph root node ID: {root_node_id}")
    knowledge_graph = knowledge_graph_service.get_knowledge_graph(
        root_node_id,
        settings.KNOWLEDGE_GRAPH_CHUNK_SIZE,
        settings.KNOWLEDGE_GRAPH_CHUNK_OVERLAP,
    )
    git_repo = repository_service.get_repository(repo_path)
    # Get git_repo pointing to container.project_path (temporary copy)
    container = GeneralContainer(repo_path)
    # Start the container with volume mapping for real-time file sync
    container.build_empty_docker_image()
    container.start_container(use_volume_mapping=True)
    container_git_repo = repository_service.get_repository(container.project_path)

    doc = {
        "test_command": "",
        "test_result": dict(),
        "env_implement_command": {
            "command": "",
            "file_content": "",
        },
        "env_implement_result": dict(),
        "env_command_result_history": [],
    }
    # Initialize the Testsuite graph
    testsuite_subgraph = TestsuiteSubgraph(
        model=llm_service.advanced_model,
        kg=knowledge_graph,
        local_path=repo_path,
        neo4j_driver=neo4j_service.neo4j_driver,
        max_token_per_neo4j_result=settings.MAX_TOKEN_PER_NEO4J_RESULT,
    )
    # Initialize the Env Implementation graph
    env_implement_subgraph = EnvImplementSubgraph(
        debug_mode=debug_mode,
        advanced_model=llm_service.advanced_model,
        base_model=llm_service.base_model,
        container=container,
        kg=knowledge_graph,
        git_repo=container_git_repo,
        neo4j_driver=neo4j_service.neo4j_driver,
        max_token_per_neo4j_result=settings.MAX_TOKEN_PER_NEO4J_RESULT,
    )
    env_repair_subgraph = EnvRepairSubgraph(
        debug_mode=debug_mode,
        test_mode=test_mode,
        advanced_model=llm_service.advanced_model,
        base_model=llm_service.base_model,
        container=container,
        kg=knowledge_graph,
        git_repo=container_git_repo,
        neo4j_driver=neo4j_service.neo4j_driver,
    )
    if not debug_mode:
        testsuite_commands = []
        logger.info("Starting testsuite...")
        if test_mode == "generation":
            try:
                testsuiteoutput_states = testsuite_subgraph.invoke(
                    max_refined_query_loop=5,
                )
                testsuite_commands = testsuiteoutput_states.get("testsuite_command", [])
                with open(
                    os.path.join(container.project_path, "prometheus_testsuite_commands.txt"), "w"
                ) as f:
                    for command in testsuite_commands:
                        f.write(command + "\n")
            except Exception as e:
                logger.error(f"Error in testsuite: {str(e)}\n{traceback.format_exc()}")
                # Clear the knowledge graph and repository
                container.cleanup()
                git_repo.reset_repository()
                logger.removeHandler(file_handler)
                file_handler.close()
                return False, None, None, None, None

        logger.info("Starting environment implementation...")
        """
        todo: 将testsuite command 作为上下文输入，重点要查找能成功运行测试的环境配置，然后执行环境配置命令。
        """
        try:
            env_output_states = env_implement_subgraph.invoke(
                recursion_limit=200,
            )
        except Exception as e:
            logger.error(f"Error in environment implementation: {str(e)}\n{traceback.format_exc()}")
            # Clear the knowledge graph and repository
            container.cleanup()
            git_repo.reset_repository()
            logger.removeHandler(file_handler)
            file_handler.close()
            return False, None, None, None, None
    else:
        if test_mode == "generation":
            with open(
                os.path.join(container.project_path, "prometheus_testsuite_commands.txt"), "r"
            ) as f:
                testsuite_commands = f.readlines()
        with open(os.path.join(container.project_path, "prometheus_setup.sh"), "r") as f:
            env_setup_bash = f.read()
        testsuiteoutput_states = {}
        env_output_states = {}

    # debug mode: 执行并交互env_implement_command和test_command
    # if debug_mode:
    doc["env_implement_command"] = {
        "command": "bash " + os.path.join(container.workdir, "prometheus_setup.sh"),
        "file_content": env_setup_bash,
    }
    if test_mode == "generation":
        doc["test_command"] = testsuite_commands

    try:
        env_implement_output = env_repair_subgraph.invoke(doc, recursion_limit=50)
    except Exception as e:
        logger.error(f"Error in environment repair: {str(e)}\n{traceback.format_exc()}")
        return False, None, None, None, None

    # Get container information
    container_info = container.print_container_info()

    # Return the states for logging
    return (
        True,
        testsuiteoutput_states,
        env_output_states,
        container_git_repo.playground_path,
        container_info,
    )


@click.command()
@click.option(
    "--dataset_file_path",
    "-d",
    required=True,
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
    default=f"projects/predictions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
)
def main(
    dataset_file_path: str,
    github_token: str,
    file: str,
):
    # 解析 all_projects.txt 文件、
    projects = parse_all_projects_file(dataset_file_path)
    logger.info(f"成功解析 {len(projects)} 个项目")

    # 初始化预测结果字典
    predictions = {}

    for project in tqdm(projects):
        # 记录当前处理的项目信息
        logger.info(f"开始处理项目: {project['name']} ")

        github_url = project["repo_url"]

        # Reproduce the bug
        success, testsuite_states, env_states, playground_path, container_info = reproduce_test(
            github_url, github_token, project['tag'], "/testbed"
        )

        # Create project result with all states
        project_result = {
            "project_name": project["name"],
            "project_repo_url": project["repo_url"],
            "success": success,
            "playground_path": str(playground_path) if playground_path else None,
            "container_info": container_info,
            "testsuite_states": serialize_states_for_json(testsuite_states)
            if testsuite_states
            else None,
            "env_states": serialize_states_for_json(env_states) if env_states else None,
            "timestamp": datetime.now().isoformat(),
        }

        # Add to predictions
        predictions[project["name"]] = project_result

        # Log the states immediately
        logger.info(f"Project {project['name']} completed successfully: {success}")
        if playground_path:
            logger.info(f"Playground path: {playground_path}")
        if container_info:
            logger.info(f"Container info: {container_info}")
        if testsuite_states:
            logger.info(f"Testsuite states keys: {list(testsuite_states.keys())}")
        if env_states:
            logger.info(f"Environment states keys: {list(env_states.keys())}")

        # Continuously save to JSON file
        with open(file, "w", encoding="utf-8") as f:
            json.dump(predictions, f, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    try:
        main()
    finally:
        # Close the Neo4j service connection
        neo4j_service.close()
