from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

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
    testsuite_command: Sequence[str]
