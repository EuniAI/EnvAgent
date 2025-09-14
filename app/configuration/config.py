from typing import Literal
from pydantic import Field, field_validator, BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class ASTNodeConfig(BaseModel):
    max_ast_depth: int = Field(gt=0, description="Maximum AST depth to traverse")
    save_ast_depth: list[int] | None = Field(
        default=None, description="AST depths to save (None means save all)"
    )
    save_declare_depth: list[int] | None = Field(
        default=None, description="Declare depths to save (None means save all)"
    )

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="PROMETHEUS_"
    )
    # Logging
    LOGGING_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    # Neo4j
    NEO4J_URI: str
    NEO4J_USERNAME: str
    NEO4J_PASSWORD: str
    NEO4J_BATCH_SIZE: int

    # Knowledge Graph
    WORKING_DIRECTORY: str
    KNOWLEDGE_GRAPH_ASTNODE_ARGS: ASTNodeConfig
    KNOWLEDGE_GRAPH_CHUNK_SIZE: int
    KNOWLEDGE_GRAPH_CHUNK_OVERLAP: int
    MAX_TOKEN_PER_NEO4J_RESULT: int

    # LLM models
    ADVANCED_MODEL: str
    BASE_MODEL: str

    # API Keys
    ANTHROPIC_API_KEY: str
    GEMINI_API_KEY: str
    VERTEX_AI_PROJECT_ID: str
    VERTEX_AI_LOCATION: str
    OPENAI_FORMAT_BASE_URL: str
    OPENAI_FORMAT_API_KEY: str

    # Model parameters
    MAX_INPUT_TOKENS: int
    TEMPERATURE: float
    MAX_OUTPUT_TOKENS: int


settings = Settings()
