"""Node: Adjust test commands based on environment maturity level and project understanding.

This node:
1. Filters out useless commands and commands that cannot test anything
2. Uses web search to supplement/modify/filter commands based on project understanding
3. Outputs adjusted test_commands dictionary
"""

from typing import Any, Dict, List, Optional
from collections import defaultdict
import functools
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import StructuredTool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from pydantic import BaseModel, Field

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger
from app.tools.web_search import WebSearchTool


class WebSearchQueryOutput(BaseModel):
    """Structured output: Web search query with level context."""

    level: str = Field(description="The level being checked: build_commands, level1_commands, level2_commands, level3_commands, or level4_commands")
    query: str = Field(description="Web search query that includes: 1) The level definition, 2) The specific command(s) being evaluated, 3) Two questions: 'Is this command appropriate for this level?' and 'What are common missing commands for this level?'. Keep query under 400 characters.")


class TestCommandAdjustmentOutput(BaseModel):
    """Structured output: Adjusted test commands by level."""

    build_commands: List[str] = Field(description="Filtered and adjusted build commands. Remove useless commands and commands that cannot test anything.")
    level1_commands: List[str] = Field(description="Filtered and adjusted level1 (entry point) commands.")
    level2_commands: List[str] = Field(description="Filtered and adjusted level2 (integration) commands.")
    level3_commands: List[str] = Field(description="Filtered and adjusted level3 (smoke test) commands.")
    level4_commands: List[str] = Field(description="Filtered and adjusted level4 (unit test) commands.")
    reasoning: str = Field(description="Brief explanation of adjustments made, including which commands were filtered and why, and any web search insights.")


class EnvRepairTestCommandAdjustNode:
    """Adjust test commands based on environment maturity and project understanding."""

    SYS_PROMPT = """\
You are a test command adjustment expert. Your task is to filter, adjust, and supplement test commands.

Test Command Levels:
1. build_commands: Commands to build and compile the project (e.g., make, npm build, mvn compile, cargo build)
2. level1_commands: Entry point commands that run the main application or service (e.g., python app.py, npm start, ./bin/server)
3. level2_commands: Integration test commands that test component interactions (e.g., integration test suites, API tests)
4. level3_commands: Smoke test commands that verify basic functionality (e.g., quick health checks, basic feature tests)
5. level4_commands: Unit test commands that test individual components in isolation (e.g., pytest, jest, go test)

Filtering Rules:
- Remove empty or whitespace-only commands
- Remove pure comments or documentation text (e.g., "# comment", "README: ...")
- Remove placeholder text (e.g., "TODO: add command", "PLACEHOLDER")
- Remove commands that cannot test anything (e.g., "echo hello", "ls", "pwd" without test assertions)
- Remove duplicate commands (keep in the most appropriate level)
- Keep commands that are valid even if unusual
- When in doubt, keep the command rather than filter it

Web Search Query Generation:
- Before calling web_search, you MUST generate a query that includes ALL of the following:
  1. The level name and its definition:
     * build_commands: Commands to build and compile the project
     * level1_commands: Entry point commands that run the main application or service
     * level2_commands: Integration test commands that test component interactions
     * level3_commands: Smoke test commands that verify basic functionality
     * level4_commands: Unit test commands that test individual components in isolation
  2. The specific command(s) you are evaluating
  3. Two explicit questions:
     a) "Is this command appropriate for this level definition?"
     b) "What are common missing commands for this level that should be added?"
- Query format example: "For build_commands (commands to build and compile the project), is 'mvn compile' appropriate for this level definition? What are common missing build commands for Maven projects that should be added?"
- Query MUST be under 400 characters. Be concise but include all required elements.
- Use web_search when you need to:
  * Check if a specific command is appropriate for a specific level definition
  * Find missing common commands for a specific level
- Call web_search tool BEFORE making final classification decisions if you're uncertain
- Use search results to supplement or modify commands, but be conservative - only add commands that are clearly relevant

Output Requirements:
- For each level (build, level1-4), provide filtered and adjusted command list
- Resolve duplicates by keeping each command in the most appropriate level
- Include reasoning explaining what was filtered and why, and any web search insights
"""

    def __init__(self, model: Optional[BaseChatModel] = None, container: Optional[BaseContainer] = None):
        self.model = model
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)
        self.web_search_tool = WebSearchTool()
        self.tools = self._init_tools()
        self.model_with_tools = model.bind_tools(self.tools) if model else None

    def _init_tools(self):
        """Initialize tools."""
        web_search_fn = functools.partial(self.web_search_tool.web_search)
        web_search_tool = StructuredTool.from_function(
            func=web_search_fn,
            name=self.web_search_tool.web_search.__name__,
            description=self.web_search_tool.web_search_spec.description,
            args_schema=self.web_search_tool.web_search_spec.input_schema,
        )
        return [web_search_tool]

    def __call__(self, state: Dict):
        """Adjust test commands: detect duplicates, then process all levels together with model."""
        test_commands = state.get("test_commands", {})

        # Step 1: Detect duplicates
        duplicate_dict = defaultdict(list)
        for key, cmds in test_commands.items():
            if isinstance(cmds, list):
                for cmd in cmds:
                    if isinstance(cmd, str) and cmd.strip():
                        duplicate_dict[cmd.strip()].append(key)
        duplicates = {cmd: levels for cmd, levels in duplicate_dict.items() if len(set(levels)) > 1}
        if duplicates:
            self._logger.info(f"Found {len(duplicates)} duplicate commands")

        # Step 2: Format input for model
        commands_text = []
        for level_key in ["build_commands", "level1_commands", "level2_commands", "level3_commands", "level4_commands"]:
            cmds = test_commands.get(level_key, [])
            if cmds:
                level_label = level_key.replace("_commands", "").replace("build", "Build").replace("level", "Level")
                commands_text.append(f"{level_label}:\n" + "\n".join([f"  - {cmd}" for cmd in cmds if isinstance(cmd, str) and cmd.strip()]))
        
        duplicate_text = ""
        if duplicates:
            duplicate_text = "\n\nDuplicate Commands (appear in multiple levels):\n"
            for cmd, levels in duplicates.items():
                duplicate_text += f"  - '{cmd}' appears in: {', '.join(levels)}\n"

        # Step 3: Invoke model with tools (allows multiple web_search calls)
        prompt = f"""\
        Current test commands:
        {chr(10).join(commands_text) if commands_text else "No commands found"}
        {duplicate_text}

        Please:
        1. Filter out useless/invalid commands
        2. Use web_search tool if needed to understand commands or find missing ones
        3. Resolve duplicates by keeping each command in the most appropriate level
        4. Supplement missing common commands if needed (be conservative)
        5. Return adjusted commands for all levels
        """

        messages = [SystemMessage(content=self.SYS_PROMPT), HumanMessage(content=prompt)]
        max_iterations = 5
        iteration = 0
        
        while iteration < max_iterations:
            response = self.model_with_tools.invoke(messages)# 可能包含 tool_calls，模型可决定是否调用工具
            messages.append(response)
            
            # Check if model wants to call tools
            if isinstance(response, AIMessage) and response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_call_id = tool_call.get('id', '')
                    tool_name = tool_call.get('name', '')
                    tool_args = tool_call.get('args', {})
                    
                    if tool_name == 'web_search':
                        original_query = tool_args.get('query', '')
                        
                        # Generate structured query using model to ensure it includes all required elements
                        try:
                            query_llm = self.model.with_structured_output(WebSearchQueryOutput) # 强制结构化输出，不能调用工具；直接返回 WebSearchQueryOutput 对象，包含 level 和 query 字段
                            query_prompt = f"""\
                            The model wants to search: {original_query}

                            Generate a complete web search query that:
                            1. Specifies the level (build_commands, level1_commands, level2_commands, level3_commands, or level4_commands) and its definition
                            2. Includes the specific command(s) being evaluated from: {original_query}
                            3. Asks: "Is this command appropriate for this level definition?"
                            4. Asks: "What are common missing commands for this level that should be added?"
                            5. Keeps total length under 400 characters

                            Return the complete query ready to use.
                            """
                            query_result = query_llm.invoke([SystemMessage(content=self.SYS_PROMPT), HumanMessage(content=query_prompt)])
                            final_query = query_result.query
                            detected_level = query_result.level
                            
                            self._logger.info(f"Web search query generated (level: {detected_level}, {len(final_query)} chars): {final_query}")
                        except Exception as e:
                            self._logger.warning(f"Failed to generate structured query: {e}, using original query")
                            final_query = original_query
                            detected_level = None
                            # Simple truncation if too long
                            if len(final_query) > 380:
                                final_query = final_query[:377] + "..."
                        
                        try:
                            search_result = self.web_search_tool.web_search(final_query, max_results=3)
                            tool_message = ToolMessage(
                                content=search_result[:1500],  # Limit length
                                tool_call_id=tool_call_id
                            )
                            messages.append(tool_message)
                        except Exception as e:
                            self._logger.warning(f"Web search failed: {e}")
                            tool_message = ToolMessage(
                                content=f"Web search failed: {str(e)}",
                                tool_call_id=tool_call_id
                            )
                            messages.append(tool_message)
                iteration += 1
                continue
            # No more tool calls, extract final response
            break
        # Step 4: Extract structured output
        try:
            # Request structured output based on conversation history
            structured_llm = self.model.with_structured_output(TestCommandAdjustmentOutput)
            final_prompt = "Based on the conversation above, please provide the final adjusted test commands in the required structured format."
            final_messages = messages + [HumanMessage(content=final_prompt)]
            result = structured_llm.invoke(final_messages)
            
            adjusted_commands = {
                "build_commands": result.build_commands,
                "level1_commands": result.level1_commands,
                "level2_commands": result.level2_commands,
                "level3_commands": result.level3_commands,
                "level4_commands": result.level4_commands,
            }
            
            self._logger.info(
                f"Final test commands: \nBuild={len(adjusted_commands.get('build_commands', []))}, adjust_commands.get('build_commands', [])={adjusted_commands.get('build_commands', [])}\n"
                f"L1={len(adjusted_commands.get('level1_commands', []))}, adjust_commands.get('level1_commands', [])={adjusted_commands.get('level1_commands', [])}\n"
                f"L2={len(adjusted_commands.get('level2_commands', []))}, adjust_commands.get('level2_commands', [])={adjusted_commands.get('level2_commands', [])}\n"
                f"L3={len(adjusted_commands.get('level3_commands', []))}, adjust_commands.get('level3_commands', [])={adjusted_commands.get('level3_commands', [])}\n"
                f"L4={len(adjusted_commands.get('level4_commands', []))}, adjust_commands.get('level4_commands', [])={adjusted_commands.get('level4_commands', [])}"
            )
            self._logger.info(f"Reasoning: {result.reasoning}")
            
            return {
                "test_commands": adjusted_commands, 
                "test_command_adjust_messages": messages + [response]
                }
            
        except Exception as e:
            self._logger.error(f"Error extracting structured output: {e}")
            return {"test_commands": test_commands,
            "test_command_adjust_messages": messages + [response]}
