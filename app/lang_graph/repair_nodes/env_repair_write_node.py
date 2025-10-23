import functools
import logging
import threading
from typing import Dict

import neo4j
from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage

from app.graph.knowledge_graph import KnowledgeGraph
from app.tools import graph_traversal
from app.utils.logger_manager import get_thread_logger
from app.tools.web_search import WebSearchTool

class EnvRepairWriteNode:
    SYS_PROMPT = """\
You are an environment repair planner. Your task is to decide the single next shell command
to install or configure dependencies so that the provided TEST COMMAND will succeed.

Input is a <context> block that contains:
- ENV IMPLEMENT COMMAND: command(s) already executed to set up the environment
- ENV IMPLEMENT OUTPUT: output from that attempt
- TEST COMMAND: the command we need to make pass
- TEST OUTPUT: output/logs from running the test (primary signal)

Instructions:
1) Carefully read TEST OUTPUT to diagnose root causes (e.g., ModuleNotFoundError, command not found,
   missing shared library, version conflict, compilation toolchain missing, OS package missing).
2) Cross-check ENV IMPLEMENT COMMAND/OUTPUT to avoid repeating ineffective steps.
3) Propose ONE next command that most likely fixes the environment. Use non-interactive flags
   (e.g., -y/--yes) and appropriate package managers or tools as indicated by the errors:
   - System packages: apt-get/yum/apk + apt-get update when needed
   - Python: pip/uv/conda; prefer exact package names from the error
   - Node.js: npm/yarn/pnpm; install missing packages or runtimes (nvm) when needed
   - Others: cargo/go/gem/composer; or create links/export vars if path issues
4) Prefer idempotent and safe commands; chain sub-steps with && where appropriate.
5) Output only the command line. No explanations, no code fences, no quotes.

Return format: a single-line shell command.
"""

    def __init__(
        self,
        model: BaseChatModel,
        kg: KnowledgeGraph,
        neo4j_driver: neo4j.Driver,
    ):
        self.web_search_tool = WebSearchTool()
        self.neo4j_driver = neo4j_driver
        self.root_node_id = kg.root_node_id
        self.tools = self._init_tools()
        self.model_with_tools = model.bind_tools(self.tools)
        self.system_prompt = SystemMessage(self.SYS_PROMPT)
        self._logger, _file_handler = get_thread_logger(__name__)

    def _init_tools(self):
        web_search_fn = functools.partial(self.web_search_tool.web_search)
        return [
            StructuredTool.from_function(
                func=web_search_fn,
                name=self.web_search_tool.web_search.__name__,
                description=self.web_search_tool.web_search_spec.description,
                args_schema=self.web_search_tool.web_search_spec.input_schema,
            )
        ]

    def __call__(self, state: Dict):
        # Ensure the context is provided as a single HumanMessage
        context_text = state["env_repair_context_query"]
        message_history = [self.system_prompt, HumanMessage(context_text)]
        response = self.model_with_tools.invoke(message_history)
        self._logger.debug(response)
        # The response will be added to the bottom of the list
        return {"env_repair_command": [response]}