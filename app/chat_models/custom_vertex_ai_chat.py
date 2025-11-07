from typing import Any, Optional

from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.prompt_values import ChatPromptValue
from langchain_core.runnables import RunnableConfig
from pydantic import Field
from vertexai import init
from vertexai.generative_models import Content, GenerativeModel, Part


class CustomVertexAIChatModel(BaseChatModel):
    """Custom Vertex AI Chat Model that wraps Google's GenerativeModel."""

    # Pydantic fields
    model_name: str = Field(description="The name of the model to use")
    project_id: str = Field(description="Google Cloud project ID")
    location: str = Field(default="us-central1", description="Google Cloud location")
    temperature: float = Field(default=0.0, description="Temperature for generation")
    max_output_tokens: int = Field(default=15000, description="Maximum output tokens")
    max_retries: int = Field(default=3, description="Maximum number of retries")

    # Non-Pydantic attributes
    model: Optional[GenerativeModel] = Field(default=None, exclude=True)

    def __init__(
        self,
        model_name: str,
        project_id: str,
        location: str = "us-central1",
        temperature: float = 0.0,
        max_output_tokens: int = 15000,
        max_retries: int = 3,
        **kwargs,
    ):
        super().__init__(
            model_name=model_name,
            project_id=project_id,
            location=location,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            max_retries=max_retries,
            **kwargs,
        )

        # Initialize Vertex AI
        init(project=project_id, location=location)

        # Initialize the model
        self.model = GenerativeModel(model_name)

    @property
    def _llm_type(self) -> str:
        return "vertex_ai_chat"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate a response from the model."""
        # Convert messages to Vertex AI format
        content_list = []
        for message in messages:
            role = "user" if isinstance(message, HumanMessage) else "model"
            try:
                content_list.append(Content(role=role, parts=[Part.from_text(message.content)]))
            except Exception as e:
                raise e

        # Generate content
        response = self.model.generate_content(
            content_list,
            generation_config={
                "temperature": self.temperature,
                "max_output_tokens": self.max_output_tokens,
            },
        )

        # Convert response to LangChain format
        text = "".join(part.text for part in response.candidates[0].content.parts)
        ai_message = AIMessage(content=text)

        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Async generate - for now, just call the sync version."""
        return self._generate(messages, stop, run_manager, **kwargs)

    def invoke(
        self,
        input: LanguageModelInput,
        config: Optional[RunnableConfig] = None,
        *,
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> BaseMessage:
        """Invoke the model."""
        # Convert input to messages
        if isinstance(input, str):
            messages = [HumanMessage(content=input)]
        elif isinstance(input, list):
            messages = input
        elif isinstance(input, ChatPromptValue):
            messages = input.messages
        else:
            messages = [input]

        result = self._generate(messages, stop=stop, **kwargs)
        return result.generations[0].message

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        """Bind tools to the model - Vertex AI has different tool binding approach."""
        # For now, return self without tool binding
        return self
