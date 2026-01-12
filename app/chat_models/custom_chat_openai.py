from typing import Any, Optional

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from app.utils.logger_manager import get_thread_logger

logger, _ = get_thread_logger(__name__)


class CustomChatOpenAI(ChatOpenAI):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        # kwargs["parallel_tool_calls"] = False
        # return super().bind_tools(tools, tool_choice=tool_choice, **kwargs)
        kwargs["parallel_tool_calls"] = False

        # Remove LangChain default sampling parameters
        for bad_key in ["temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty"]:
            if bad_key in kwargs:
                kwargs.pop(bad_key)

        runnable = super().bind_tools(tools, tool_choice=tool_choice, **kwargs)

        # Clear inherited default sampling params
        return runnable.bind()

    def invoke(
        self,
        input: LanguageModelInput,
        config: Optional[RunnableConfig] = None,
        *,
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> BaseMessage:
        response = super().invoke(
            input=input,
            config=config,
            stop=stop,
            **kwargs,
        )
        
        # 计算并输出 token 使用信息
        self._log_token_usage(response)
        
        return response
    
    def _log_token_usage(self, response: BaseMessage) -> None:
        """从响应中提取并输出 token 使用信息"""
        try:
            # 尝试从 response_metadata 中获取 token 使用信息（OpenAI 格式）
            if hasattr(response, 'response_metadata') and response.response_metadata:
                # response_metadata 可能是字典
                response_metadata = response.response_metadata
                if isinstance(response_metadata, dict):
                    token_usage = response_metadata.get('token_usage', {})
                else:
                    token_usage = getattr(response_metadata, 'token_usage', {})
                
                if token_usage:
                    if isinstance(token_usage, dict):
                        prompt_tokens = token_usage.get('prompt_tokens', 0)
                        completion_tokens = token_usage.get('completion_tokens', 0)
                        total_tokens = token_usage.get('total_tokens', 0)
                    else:
                        prompt_tokens = getattr(token_usage, 'prompt_tokens', 0)
                        completion_tokens = getattr(token_usage, 'completion_tokens', 0)
                        total_tokens = getattr(token_usage, 'total_tokens', 0)
                    
                    if prompt_tokens or completion_tokens:
                        logger.info(
                            f"Token Usage - Prompt: {prompt_tokens:,}, "
                            f"Completion: {completion_tokens:,}, "
                            f"Total: {total_tokens:,}"
                        )
                        return
            
            # 如果没有 response_metadata，尝试从 usage_metadata 获取（Anthropic 格式）
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage_metadata = response.usage_metadata
                if isinstance(usage_metadata, dict):
                    input_tokens = usage_metadata.get('input_tokens', 0)
                    output_tokens = usage_metadata.get('output_tokens', 0)
                else:
                    input_tokens = getattr(usage_metadata, 'input_tokens', 0)
                    output_tokens = getattr(usage_metadata, 'output_tokens', 0)
                
                if input_tokens or output_tokens:
                    logger.info(
                        f"Token Usage - Input: {input_tokens:,}, "
                        f"Output: {output_tokens:,}, "
                        f"Total: {input_tokens + output_tokens:,}"
                    )
                    return
                
        except Exception as e:
            logger.debug(f"Failed to extract token usage: {e}")
