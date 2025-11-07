from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from app.chat_models.custom_chat_openai import CustomChatOpenAI
from app.chat_models.custom_vertex_ai_chat import CustomVertexAIChatModel
from app.services.base_service import BaseService


class LLMService(BaseService):
    def __init__(
        self,
        advanced_model_name: str,
        base_model_name: str,
        openai_format_api_key: Optional[str] = None,
        openai_format_base_url: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        vertex_ai_project_id: Optional[str] = None,
        vertex_ai_location: Optional[str] = "us-central1",
        temperature: float = 0.0,
    ):
        self.advanced_model = get_model(
            advanced_model_name,
            openai_format_api_key,
            openai_format_base_url,
            anthropic_api_key,
            gemini_api_key,
            vertex_ai_project_id,
            vertex_ai_location,
            temperature,
        )
        self.base_model = get_model(
            base_model_name,
            openai_format_api_key,
            openai_format_base_url,
            anthropic_api_key,
            gemini_api_key,
            vertex_ai_project_id,
            vertex_ai_location,
            temperature,
        )


def get_model(
    model_name: str,
    openai_format_api_key: Optional[str] = None,
    openai_format_base_url: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    vertex_ai_project_id: Optional[str] = None,
    vertex_ai_location: Optional[str] = None,
    temperature: float = 0.0,
) -> BaseChatModel:
    if "claude" in model_name:
        return ChatAnthropic(
            model_name=model_name,
            api_key=anthropic_api_key,
            temperature=temperature,
            max_retries=3,
        )
    elif "gemini" in model_name and vertex_ai_project_id:
        # Use Vertex AI for Gemini models when project_id is provided
        return CustomVertexAIChatModel(
            model_name=model_name,
            project_id=vertex_ai_project_id,
            location=vertex_ai_location,
            temperature=temperature,
            max_retries=3,
        )
    elif "gemini" in model_name:
        # Use Google AI Studio API for Gemini models
        return ChatGoogleGenerativeAI(
            model=model_name,
            api_key=gemini_api_key,
            temperature=temperature,
            max_retries=3,
        )
    else:
        """
        Use tiktoken_counter to ensure that the input messages do not exceed the maximum token limit.
        """
        return CustomChatOpenAI(
            model=model_name,
            api_key=openai_format_api_key,
            base_url=openai_format_base_url,
            temperature=temperature,
            max_retries=3,
        )
