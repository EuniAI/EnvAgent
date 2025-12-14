from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from pathlib import Path
import json
import time
from typing import Annotated, Any, Dict, Sequence, TypedDict

timestamp = time.strftime('%Y%m%d_%H%M%S')

# class TestsuiteState(TypedDict):
#     max_refined_query_loop: int

#     testsuite_query: str
#     testsuite_file_context: Annotated[Sequence[BaseMessage], add_messages]
#     testsuite_context: Sequence[Context]
#     testsuite_refined_query: str

#     # testsuite_write_messages: Annotated[Sequence[BaseMessage], add_messages]
#     # testsuite_file_messages: Annotated[Sequence[BaseMessage], add_messages]
#     # testsuite_execute_messages: Annotated[Sequence[BaseMessage], add_messages]

#     # bug_reproducing_patch: str

#     # reproduced_bug: bool
#     # reproduced_bug_failure_log: str
#     # reproduced_bug_file: Path
#     # reproduced_bug_commands: Sequence[str]


class TestsuiteState(TypedDict):
    query: str
    testsuite_max_refined_query_loop: int

    testsuite_context_provider_messages: Annotated[Sequence[BaseMessage], add_messages]
    testsuite_refined_query: str
    testsuite_command: Annotated[Sequence[str], add_messages]
    involved_commands: Sequence[str]  # Track all commands that have been searched to prevent duplicate searches
    involved_files: Sequence[str]  # Track all files that have been searched to prevent duplicate searches
    
    # Test classification results (commands organized by level)
    testsuite_level1_commands: Annotated[Sequence[str], add_messages]
    testsuite_level2_commands: Annotated[Sequence[str], add_messages]
    testsuite_level3_commands: Annotated[Sequence[str], add_messages]
    testsuite_level4_commands: Annotated[Sequence[str], add_messages]
    
    # Test execution plan (ordered sequence)
    testsuite_execution_plan: Annotated[Sequence[dict], add_messages]
    
    # CI/CD workflow information
    testsuite_cicd_workflow_files: Sequence[str]
    testsuite_cicd_workflow_contents: Sequence[dict]  # List of dicts with "relative_path" and "content" keys
    testsuite_cicd_workflow_summaries: dict[str, str]  # LLM-extracted test commands and setup steps
    testsuite_cicd_extracted_commands: Sequence[str]

def pydantic_encoder(obj: Any) -> Any:
    """ 
    一个自定义的编码器，用于在遇到 BaseModel 实例时，将其转换为字典。
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump() 
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def save_testsuite_states_to_json(states: TestsuiteState, project_path: Path):
    FILE_PATH = f"{project_path}/prometheus_testsuite_states_{timestamp}.json"
    with open(FILE_PATH, "w") as f:
        json.dump(states, f, default=pydantic_encoder, indent=4, ensure_ascii=False)

def load_testsuite_states_from_json(project_path: Path) -> TestsuiteState:
    FILE_PATH = f"{project_path}/prometheus_testsuite_states_{timestamp}.json"
    with open(FILE_PATH, "r") as f:
        return json.load(f)