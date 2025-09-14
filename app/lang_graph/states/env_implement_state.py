from pathlib import Path
from typing import Annotated, Mapping, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.models.context import Context


class EnvImplementState(TypedDict):
    # Query refinement control
    max_refined_query_loop: int  # Maximum number of query refinement iterations

    # Environment implementation context
    env_implement_query: str  # The refined query for environment implementation
    env_implement_context: Sequence[Context]  # Contextual information for environment setup

    # Message sequences for different operations
    env_implement_file_context_query: str  # The refined query for environment implementation file context  
    env_implement_file_context: Sequence[Context] # The context for environment implementation file 
    
    env_implement_write_messages: Annotated[Sequence[BaseMessage], add_messages]  # Messages for write operations
    env_implement_file_messages: Annotated[Sequence[BaseMessage], add_messages]  # Messages for file operations
    env_implement_execute_messages: Annotated[Sequence[BaseMessage], add_messages]  # Messages for execution operations

    # Dockerfile auto-generation related
    dockerfile_content: str  # Generated Dockerfile content as string
    dockerfile_path: Path  # File path where the Dockerfile will be saved
    dockerfile_failure_log: str  # Error logs if Dockerfile generation failed

    # # Auto-configuration files related
    # config_files: Sequence[Mapping[str, str]]  # Mapping of filename -> content for configuration files
    # config_files_generated: bool  # Flag indicating if configuration files were successfully generated
    # config_validation_log: str  # Logs for configuration file validation

    # # Environment setup
    # environment_setup_commands: Sequence[str]  # List of commands needed to set up the environment
    # environment_ready: bool  # Flag indicating if the environment is ready for use
    # environment_setup_log: str  # Logs from environment setup process
