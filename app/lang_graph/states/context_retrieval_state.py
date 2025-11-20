from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.models.context import Context


class ContextRetrievalState(TypedDict):
    query: str
    max_refined_query_loop: int

    context_provider_messages: Annotated[Sequence[BaseMessage], add_messages]
    refined_query: str
    context: Sequence[Context]
    involved_files: Sequence[str]  # Files that have been searched (found or not found), to avoid repeated searches
