import json
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path, PosixPath
from threading import Lock
from typing import Any, Dict, List, Optional

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


GITHUB_HTTPS_URL = "https://github.com/{repo_name}.git"

logger, file_handler = get_thread_logger(__name__)
debug_mode = True
repair_only_run_env_execute = False
repair_only_run_test_execute = True
test_mode = "generation"  # generation pyright pytest CI/CD


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
    文件格式：项目名 标签 [项目路径] [dockerfile模板路径]
    Args:
        file_path: all_projects.txt 文件的路径
    Returns:
        包含项目信息的字典列表，每个字典包含：
        - name: 项目名称
        - repo_url: 仓库URL
        - tag: 项目标签
        - project_path: 项目路径（可选）
        - dockerfile_template: Dockerfile模板路径（可选）
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
                
                if len(parts) >= 3:
                    project_path = parts[2]
                    project_info["project_path"] = project_path
                else:
                    project_info["project_path"] = None

                if len(parts) >= 4:
                    docker_image_name = parts[3]
                    project_info["docker_image_name"] = docker_image_name
                else:
                    project_info["docker_image_name"] = None


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
    project_dir: Path,
    project_path: Optional[str] = None,
    dockerfile_template_path: Optional[str] = None,
    docker_image_name: Optional[str] = None,
) -> tuple[bool, None, None, None, None] | tuple[bool, Dict, Dict, str, str]:
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

    # if project_path is provided, use it to create new temp project path, otherwise create new temp project path from repo_path
    project_path = Path(project_path) if project_path else repo_path
    # Get git_repo pointing to container.project_path (temporary copy)
    # Convert dockerfile_template_path to Path if provided
    dockerfile_path = None
    if dockerfile_template_path:
        dockerfile_path = Path(dockerfile_template_path)
        if not dockerfile_path.is_absolute():
            # If relative path, resolve relative to the main.py file's directory
            main_dir = Path(__file__).parent.parent
            dockerfile_path = (main_dir / dockerfile_template_path).resolve()
    container = GeneralContainer(
        project_path,
        project_dir=project_dir,
        dockerfile_template_path=dockerfile_path,
        docker_image_name=docker_image_name,
    )
    # Start the container with volume mapping for real-time file sync
    container.build_docker_image()
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
        test_mode=test_mode,
        container=container,
        kg=knowledge_graph,
        # local_path=repo_path,
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
        test_mode=test_mode,
    )
    env_repair_subgraph = EnvRepairSubgraph(
        debug_mode=debug_mode,
        test_mode=test_mode,
        repair_only_run_env_execute=repair_only_run_env_execute,
        repair_only_run_test_execute=repair_only_run_test_execute,
        advanced_model=llm_service.advanced_model,
        base_model=llm_service.base_model,
        container=container,
        kg=knowledge_graph,
        git_repo=container_git_repo,
        neo4j_driver=neo4j_service.neo4j_driver,
    )
    
    if debug_mode:
        logger.info(f"parse testsuite commands...")
        try:
            testsuiteoutput_states = testsuite_subgraph.invoke(max_refined_query_loop=5,)
            testsuite_commands_raw = testsuiteoutput_states.get("testsuite_commands", [])
            testsuite_commands_level = {
                "build_commands": list(set(testsuite_commands_raw.get("testsuite_build_commands", []))),
                "level1_commands": list(set(testsuite_commands_raw.get("testsuite_level1_commands", []))),
                "level2_commands": list(set(testsuite_commands_raw.get("testsuite_level2_commands", []))),
                "level3_commands": list(set(testsuite_commands_raw.get("testsuite_level3_commands", []))),
                "level4_commands": list(set(testsuite_commands_raw.get("testsuite_level4_commands", []))),
            }
            testsuite_commands = testsuite_commands_level
        except Exception as e:
            logger.debug(f"Error in testsuite commands: {str(e)}")

        # with open(os.path.join(container.project_path, "prometheus_testsuite_commands.json"), "w") as f:
        #     json.dump(testsuite_commands, f, indent=4, ensure_ascii=False)

        # logger.info(f"start environment implementation...")
        # try:
        #     # env_output_states = env_implement_subgraph.invoke(recursion_limit=200, testsuite_commands=testsuite_commands)
        #     env_output_states = env_implement_subgraph.invoke(recursion_limit=200, testsuite_commands=None)
        # except Exception as e:
        #     logger.error(f"Error in environment implementation: {str(e)}\n{traceback.format_exc()}")
        #     return (
        #         False,
        #         {},
        #         {},
        #         container_git_repo.playground_path,
        #         container.print_container_info(),
        #     )


        logger.info(f"parse env setup bash...")
        with open(os.path.join(container.project_path, "prometheus_setup.sh"), "r") as f:
            env_setup_bash = f.read()

        logger.info(f"start env repair...")
        doc["env_implement_command"] = {
            "command": "bash " + os.path.join(container.workdir, "prometheus_setup.sh"),
            "file_content": env_setup_bash,
        }
        # with open(os.path.join(container.project_path, "prometheus_testsuite_commands.json"), "r") as f:
        #     testsuite_commands_level = json.load(f)
        #     testsuite_commands_level = {
        #         "build_commands": list(set(testsuite_commands_level.get("testsuite_build_commands", []))),
        #         "level1_commands": list(set(testsuite_commands_level.get("testsuite_level1_commands", []))),
        #         "level2_commands": list(set(testsuite_commands_level.get("testsuite_level2_commands", []))),
        #         "level3_commands": list(set(testsuite_commands_level.get("testsuite_level3_commands", []))),
        #         "level4_commands": list(set(testsuite_commands_level.get("testsuite_level4_commands", []))),
        #     }
        #     testsuite_commands = testsuite_commands_level #[command for level in testsuite_commands_level.values() for command in level]
        doc["test_commands"] = testsuite_commands

        try:
            env_implement_output = env_repair_subgraph.invoke(doc, recursion_limit=settings.REPAIR_RECURSION_LIMIT)
        except Exception as e:
            logger.error(f"Error in environment repair: {str(e)}\n{traceback.format_exc()}")
            return (
                False,
                {},
                {},
                container_git_repo.playground_path,
                container.print_container_info(),
            )

        return (
                True,
                {},
                {},
                container_git_repo.playground_path,
                container.print_container_info(),
            )


    
    elif not debug_mode:
        testsuite_commands = []
        logger.info("Starting testsuite...")
        try:
            testsuiteoutput_states = testsuite_subgraph.invoke(max_refined_query_loop=10,)
            if test_mode == "generation":
                # 改成 build + level1-4
                testsuite_commands = {
                    "build_commands": [command.content for command in testsuiteoutput_states.get("testsuite_build_commands", [])],
                    "level1_commands": [command.content for command in testsuiteoutput_states.get("testsuite_level1_commands", [])],
                    "level2_commands": [command.content for command in testsuiteoutput_states.get("testsuite_level2_commands", [])],
                    "level3_commands": [command.content for command in testsuiteoutput_states.get("testsuite_level3_commands", [])],
                    "level4_commands": [command.content for command in testsuiteoutput_states.get("testsuite_level4_commands", [])],
                }
            elif test_mode == "CI/CD":
                testsuite_commands = testsuiteoutput_states.get("testsuite_cicd_extracted_commands", [])


            with open(os.path.join(container.project_path, "prometheus_testsuite_commands.json"), "w") as f:
                json.dump(testsuite_commands, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error in testsuite: {str(e)}\n{traceback.format_exc()}")
            # Clear the knowledge graph and repository
            # container.cleanup()
            # git_repo.reset_repository()
            # logger.removeHandler(file_handler)
            # file_handler.close()
            return (
                False,
                {},
                {},
                container_git_repo.playground_path,
                container.print_container_info(),
            )

        logger.info(f"parse testsuite commands...")
        if test_mode == "generation":
            with open(
                os.path.join(container.project_path, "prometheus_testsuite_commands.json"), "r"
            ) as f:
                testsuite_commands = json.load(f)
        logger.info("Starting environment implementation...")
        """
        todo: 将testsuite command 作为上下文输入，重点要查找能成功运行测试的环境配置，然后执行环境配置命令。
        """
        try:
            env_output_states = env_implement_subgraph.invoke(recursion_limit=200, testsuite_commands=testsuite_commands)
        except Exception as e:
            logger.error(f"Error in environment implementation: {str(e)}\n{traceback.format_exc()}")
            return (
                False,
                {},
                {},
                container_git_repo.playground_path,
                container.print_container_info(),
            )

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
            env_implement_output = env_repair_subgraph.invoke(doc, recursion_limit=settings.REPAIR_RECURSION_LIMIT)
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
# @click.option(
#     "--file",
#     "-f",
#     help="File to save the predictions or continue patch generating.",
#     default=f"projects/predictions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
# )
@click.option(
    "--max_workers",
    "-w",
    help="max_workers: maximum number of threads, default is 4",
    default=4,
    type=int,
)
@click.option(
    "--dockerfile_template",
    "-t",
    help="Path to Dockerfile template file (e.g., projects/dockerfile/python-pyright.dockerfile). "
         "If not provided, uses the default Dockerfile content.",
    default=None,
    type=str,
)
@click.option(
    "--docker_image_name",
    "-i",
    help="Docker image name to use for the container.",
    default=None,
    type=str,
)
def main(
    dataset_file_path: str,
    github_token: str,
    # file: str,
    max_workers: int,
    dockerfile_template: Optional[str],
    docker_image_name: Optional[str],
):
    # 解析 all_projects.txt 文件、
    projects = parse_all_projects_file(dataset_file_path)
    logger.info(f"成功解析 {len(projects)} 个项目")

    # 初始化预测结果字典和锁
    project_dir = Path(settings.WORKING_DIRECTORY) / "projects" / datetime.now().strftime("%Y%m%d_%H%M%S")
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / "project_results.json"
    predictions = {}
    predictions_lock = Lock()

    def process_project(project: Dict[str, str]) -> tuple[str, Dict[str, Any]]:
        """处理单个项目的函数，用于多线程执行"""
        project_name = project["name"]
        try:
            # 记录当前处理的项目信息
            logger.info(f"开始处理项目: {project_name} ")

            github_url = project["repo_url"]

            # Get dockerfile template path from project info or use global template
            # Prefer project-specific template, fall back to global template
            project_dockerfile = project.get("dockerfile_template") or dockerfile_template
            project_docker_image_name = project.get("docker_image_name") or docker_image_name
            project_path = project.get("project_path")
            # Reproduce the bug
            success, testsuite_states, env_states, playground_path, container_info = reproduce_test(
                github_url, github_token, project['tag'],
                project_dir=project_dir, 
                dockerfile_template_path=project_dockerfile, 
                project_path=project_path,
                docker_image_name=project_docker_image_name,
            )

            # Create project result with all states
            project_result = {
                "project_name": project_name,
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

            # Log the states immediately
            logger.info(f"Project {project_name} completed successfully: {success}")
            if playground_path:
                logger.info(f"Playground path: {playground_path}")
            if container_info:
                logger.info(f"Container info: {container_info}")
            if testsuite_states:
                logger.info(f"Testsuite states keys: {list(testsuite_states.keys())}")
            if env_states:
                logger.info(f"Environment states keys: {list(env_states.keys())}")

            return project_name, project_result

        except Exception as e:
            # 捕获所有异常，记录错误信息并继续处理下一个项目
            error_message = str(e)
            error_traceback = traceback.format_exc()
            logger.error(f"处理项目 {project_name} 时发生错误: {error_message}")
            logger.error(f"错误堆栈:\n{error_traceback}")

            # 创建错误结果
            project_result = {
                "project_name": project_name,
                "project_repo_url": project.get("repo_url", "unknown"),
                "success": False,
                "error": error_message,
                "error_traceback": error_traceback,
                "playground_path": None,
                "container_info": None,
                "testsuite_states": None,
                "env_states": None,
                "timestamp": datetime.now().isoformat(),
            }

            return project_name, project_result

    # 使用线程池并行处理项目
    logger.info(f"使用 {max_workers} 个线程并行处理项目")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_project = {
            executor.submit(process_project, project): project for project in projects
        }

        # project 的json结果，保存到Data的文件夹中。并且每次运行都mkdir一个文件夹，用来将文件夹
        # 使用tqdm显示进度
        with tqdm(total=len(projects), desc="处理项目") as pbar:
            for future in as_completed(future_to_project):
                try:
                    project_name, project_result = future.result()
                    # 线程安全地更新predictions字典
                    with predictions_lock:
                        predictions[project_name] = project_result
                        # 保存当前进度到 JSON 文件
                        try:
                            with open(project_file, "w", encoding="utf-8") as f:
                                json.dump(predictions, f, indent=4, ensure_ascii=False)
                        except Exception as save_error:
                            logger.error(f"保存结果文件时发生错误: {save_error}")
                except Exception as e:
                    logger.error(f"获取任务结果时发生错误: {str(e)}")
                finally:
                    pbar.update(1)

    logger.info(f"所有项目处理完成，结果已保存到 {project_file}")


if __name__ == "__main__":
    try:
        main()
    finally:
        # Close the Neo4j service connection
        neo4j_service.close()
