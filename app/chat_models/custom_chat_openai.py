from typing import Any, Optional

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage, trim_messages
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from app.configuration.config import settings
from app.utils.llm_util import tiktoken_counter


class CustomChatOpenAI(ChatOpenAI):
    def bind_tools(self, tools, tool_choice=None, **kwargs):
        kwargs["parallel_tool_calls"] = False
        return super().bind_tools(tools, tool_choice=tool_choice, **kwargs)

    def invoke(
        self,
        input: LanguageModelInput,
        config: Optional[RunnableConfig] = None,
        *,
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> BaseMessage:
        return super().invoke(
            input=trim_messages(
                input,
                token_counter=tiktoken_counter,
                strategy="last",
                max_tokens=settings.MAX_INPUT_TOKENS,
                start_on="human",
                end_on=("human", "tool"),
                include_system=True,
            ),
            config=config,
            stop=stop,
            **kwargs,
        )
