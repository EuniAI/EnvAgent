import json
import os
import time
from pathlib import Path
from typing import Annotated, Any, Dict, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from app.models.context import Context

timestamp = time.strftime('%Y%m%d_%H%M%S')

class EnvImplementState(TypedDict):
    # Query refinement control
    max_refined_query_loop: int  # Maximum number of query refinement iterations

    # Environment implementation context
    env_implement_query: str  # The refined query for environment implementation
    env_implement_context: Sequence[Context]  # Contextual information for environment setup

    # Message sequences for different operations
    env_implement_file_context_query: (
        str  # The refined query for environment implementation file context
    )
    env_implement_file_context: Sequence[Context]  # The context for environment implementation file

    env_implement_write_messages: Annotated[
        Sequence[BaseMessage], add_messages
    ]  # Messages for write operations
    env_implement_file_messages: Annotated[
        Sequence[BaseMessage], add_messages
    ]  # Messages for file operations
    env_implement_execute_messages: Annotated[
        Sequence[BaseMessage], add_messages
    ]  # Messages for execution operations

    # Dockerfile auto-generation related
    env_implement_bash_content: str  # Generated Dockerfile content as string
    env_implement_bash_path: Path  # File path where the Dockerfile will be saved
    testsuites_failure_log: str  # Error logs if testsuites generation failed

    # -------repair related-------
    env_implement_command: Dict[
        str, Any
    ]  # （首次生成的）完整的bashfile配置命令（可以被新加入和整合）,包含文件路径，以及文件内容，都需要被记录
    env_implement_command_messages: Annotated[
        Sequence[BaseMessage], add_messages
    ]  # Messages for command update tool execution
    env_implement_result: Dict[
        str, Any
    ]  # 运行env_implement_command的结果 包含（退出码、标准输出、标准错误）
    # env_repair_context_query: Sequence[Context]  # The refined query for environment repair context （什么意思，后面再确认一下）
    env_repair_command: Sequence[str]  # 根据分析，得到的可以补充到env_implement_command中的命令列表
    env_command_result_history: Sequence[
        Dict[str, Any]
    ]  # 所有env_command以及其运行的结果 包含（env_implement_command（文件路径、文件内容），env_implement_result（退出码、标准输出、标准错误）, analysis（错误分析））

    test_command: Sequence[Context]  # 查找得到的testsuite
    test_result: Sequence[Dict[str, Any]]  # 运行testsuite的结果
    test_command_result_history: Sequence[
        Dict[str, Any]
    ]  # 所有test_command以及其运行的结果 包含（test_command，test_result, analysis（错误分析））

    env_error_analysis: str  # 分析test_result或者env_implement_result中的错误原因
    check_state: Dict[str, Any]



def pydantic_encoder(obj: Any) -> Any:
    """
    一个自定义的编码器，用于在遇到 BaseModel 实例时，将其转换为字典。
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump() 
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def save_env_implement_states_to_json(states: EnvImplementState, project_path: Path):
    FILE_PATH = f"{project_path}/prometheus_env_implement_states_{timestamp}.json"
    with open(FILE_PATH, "w") as f:
        json.dump(states, f, default=pydantic_encoder, indent=4, ensure_ascii=False)

def load_env_implement_states_from_json(project_path: Path) -> EnvImplementState:
    FILE_PATH = f"{project_path}/prometheus_env_implement_states_{timestamp}.json"
    with open(FILE_PATH, "r") as f:
        return json.load(f)