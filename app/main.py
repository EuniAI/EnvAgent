import json
import threading
import traceback
from datetime import datetime
from typing import Dict, List

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
from app.utils.logger_manager import get_thread_logger
from app.lang_graph.subgraphs.env_implement_subgraph import EnvImplementSubgraph
from app.lang_graph.subgraphs.testsuite_subgraph import TestsuiteSubgraph
# SWEBENCH_IMAGE_FORMAT = "swebench/sweb.eval.x86_64.{repo_prefix}_1776_{instance_id}:v1"

GITHUB_HTTPS_URL = "https://github.com/{repo_name}.git"

logger, file_handler = get_thread_logger(__name__)


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
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                    
                # 按空格分割，但URL可能包含空格，需要特殊处理
                parts = line.split()
                if len(parts) < 4:
                    logger.warning(f"第{line_num}行格式不正确，跳过: {line}")
                    continue
                
                # 前三个部分分别是：项目名、仓库URL、编程语言
                project_name = parts[0]
                language = parts[-2]  # 倒数第二个是编程语言
                image_full = parts[-1]  # 最后一个是镜像名:标签
                
                # 处理镜像名和标签
                if ':' in image_full:
                    image_name, tag = image_full.rsplit(':', 1)
                else:
                    image_name = image_full
                    tag = 'latest'
                
                # 仓库URL是中间部分，需要重新组合（因为URL可能包含空格）
                repo_url_parts = parts[1:-2]
                repo_url = ' '.join(repo_url_parts)
                
                project_info = {
                    'name': project_name,
                    'repo_url': repo_url,
                    'language': language,
                    'image': image_name,
                    'tag': tag
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
    max_output_tokens=settings.MAX_OUTPUT_TOKENS,
)


def reproduce_test(
    github_url: str,
    github_token: str,
    # commit_id: str = None,
    # dockerfile_content: str = None,
    image_name: str = None,
    # build_commands: Sequence[str] = None,
    # test_commands: Sequence[str] = None,
    workdir: str = None,
) -> tuple[bool, None, None, None] | tuple[bool, str, str, str]:

    # if dockerfile_content or image_name:
    if workdir is None:
        raise Exception("workdir must be provided for user defined environment")
    # Get or create repository (repository-based logic)
    logger.info("Getting or creating repository...")
    repo_path, root_node_id, is_new_repository = repository_service.get_or_create_repository(
        github_token, github_url
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
    container.build_docker_image()
    container.start_container(use_volume_mapping=True)
    container_git_repo = repository_service.get_repository(container.project_path)
    

    # testsuite_subgraph = TestsuiteSubgraph(
    #     model=llm_service.advanced_model,
    #     kg=knowledge_graph,
    #     local_path=repo_path,
    #     neo4j_driver=neo4j_service.neo4j_driver,
    #     max_token_per_neo4j_result = settings.MAX_TOKEN_PER_NEO4J_RESULT,
    # )
    # logger.info("Starting testsuite...")
    # try:
    #     testsuiteoutput_states = testsuite_subgraph.invoke(
    #         max_refined_query_loop=5,
    #     )
    # except Exception as e:
    #     logger.error(f"Error in testsuite: {str(e)}\n{traceback.format_exc()}")
    #     # Clear the knowledge graph and repository
    #     container.cleanup()
    #     git_repo.reset_repository()
    #     logger.removeHandler(file_handler)
    #     file_handler.close()
    #     return False, None, None, None

    testsuiteoutput_states = {'testsuite_command': ['mvn --version', 'java -version', 'git --version', 'find flink-yarn-tests/target -name "*.err" -or -name "*.out"', 'node --version', 'npm run lint', 'python --version', 'pip --version', './dev/lint-python.sh', 'hadoop version', 'docker --version', 'docker compose --version', 'openssl version', 'keytool -help', 'mvn test -Dtest="*TestCodeArchitectureTest*" -DfailIfNoTests=false -Dfast', 'hugo version']}

    # Initialize the bug reproduce graphfadb9c9ed1c7
    env_implement_subgraph = EnvImplementSubgraph(
        advanced_model=llm_service.advanced_model,
        base_model=llm_service.base_model,
        container=container,
        kg=knowledge_graph,
        git_repo=container_git_repo,
        neo4j_driver=neo4j_service.neo4j_driver,
        max_token_per_neo4j_result=settings.MAX_TOKEN_PER_NEO4J_RESULT,
    )

    # Invoke the bug reproduction subgraph
    logger.info("Starting environment implementation...")
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
        return False, None, None, None
        
    if is_new_repository:
        repository_service.clean_repository(github_url)
        logger.info("Cleaned up new repository resources")
    else:
        logger.info("Keeping existing repository resources for reuse")
    
    # Get generated files from container (including Dockerfile)
    generated_dockerfile = container.get_dockerfile_from_container()
    if generated_dockerfile:
        logger.info(f"Generated Dockerfile found at: {generated_dockerfile}")
        # Read the content of the generated Dockerfile
        try:
            with open(generated_dockerfile, 'r', encoding='utf-8') as f:
                generated_dockerfile_content = f.read()
            logger.info(f"Generated Dockerfile content:\n{generated_dockerfile_content}")
            # Update the output states with the actual generated file
            output_states['dockerfile_path'] = generated_dockerfile
            output_states['dockerfile_content'] = generated_dockerfile_content
        except Exception as e:
            logger.error(f"Error reading generated Dockerfile: {e}")
    
    logger.info(f"context files: {output_states['env_implement_file_context']}")
    logger.info(f"dockerfile path: {output_states['dockerfile_path']}")
    logger.info(f"dockerfile content: {output_states['dockerfile_content']}")
    return output_states

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
    default=f"predictions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
)
def main(
    dataset_file_path: str,
    github_token: str,
    file: str,
):
    
    # dataset = load_dataset(dataset_name)
    # filtered_dataset = dataset["test"]
    # print(f"Dataset loaded: {dataset_name}")
    
    # 解析 all_projects.txt 文件、
    projects = parse_all_projects_file(dataset_file_path)
    logger.info(f"成功解析 {len(projects)} 个项目")

    # 初始化预测结果字典
    predictions = {}

    for project in tqdm(projects):
        # 记录当前处理的项目信息
        logger.info(f"开始处理项目: {project['name']} ({project['language']})")
        
        # Get Issue information
        # repo_prefix = github_issue["repo"].split("/")[0]
        # instance_id = github_issue["instance_id"].split("__")[-1]
        # image_name = SWEBENCH_IMAGE_FORMAT.format(repo_prefix=repo_prefix, instance_id=instance_id)
        # github_url = GITHUB_HTTPS_URL.format(repo_name=github_issue["repo"])
        # commit_id = github_issue["base_commit"]
        # problem_statement_lines = github_issue["problem_statement"].splitlines()
        # issue_title = problem_statement_lines[0]
        # issue_body = "\n".join(problem_statement_lines[1:])

        github_url = project["repo_url"]
        language = project["language"]
        image_name = project["image"]

        # Reproduce the bug
        output_states = reproduce_test(github_url, github_token, image_name, "/testbed")
        
        # predictions[github_ds["instance_id"]] = {
        #     "reproduced_bug": reproduced_bug,
        #     "reproduced_bug_file": str(reproduced_bug_file),
        #     "reproduced_bug_commands": reproduced_bug_commands,
        #     "reproduced_bug_patch": reproduced_bug_patch,
        # }

        with open(file, "w", encoding="utf-8") as f:
            json.dump(predictions, f, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    try:
        main()
    finally:
        # Close the Neo4j service connection
        neo4j_service.close()
