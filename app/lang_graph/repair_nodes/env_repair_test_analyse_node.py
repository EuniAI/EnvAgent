"""节点：分析 test_result_history 中的错误"""

import functools
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger
from app.utils.str_util import pre_append_line_numbers


class ReadFileInput(BaseModel):
    file_path: str = Field(description="文件的路径，可以是绝对路径（如 /app/prometheus_setup.sh）或相对路径")


READ_FILE_DESCRIPTION = """\
读取指定路径的文件内容并添加行号。文件路径是容器内的路径（如 /app/prometheus_setup.sh）。
默认返回前1000行以防止大文件导致上下文过长。
如果文件不存在，将返回错误消息。
"""


class RepairCommandsOutput(BaseModel):
    """结构化输出：包含下一步修复指令列表"""
    error_analysis: str = Field(description="对错误的详细分析")
    repair_commands: List[str] = Field(
        description="下一步需要执行的具体修复指令列表。每个指令应该是可以直接执行的 shell 命令，使用非交互式标志（如 -y/--yes）。"
    )


class EnvRepairTestAnalyseNode:
    """分析测试命令执行结果中的错误并生成修复命令"""
    
    SYS_PROMPT = """\
你是一个环境修复分析专家。你的任务是分析测试命令执行的历史结果，识别错误原因，并生成具体的修复指令列表。

输入包含：
- TEST COMMAND HISTORY: 最后3轮的测试命令执行历史和结果
- CURRENT TEST RESULTS: 当前最新的测试结果

你的任务分为三部分：

第一部分：错误分析
1. 仔细分析当前测试结果中的错误信息
2. 识别根本原因（如：模块未找到、命令不存在、缺少共享库、版本冲突、环境配置问题等）
3. 分析为什么测试失败
4. 提供详细的错误分析总结

第二部分：历史反思
如果提供了 TEST COMMAND HISTORY（最后3轮历史），你需要：
1. 对比当前错误与历史轮次中的错误
2. 判断当前错误是否与历史错误相同或相似
3. 如果错误一直出现（重复了多轮），说明之前的修复策略可能无效
4. 在这种情况下，你需要：
   - 反思为什么之前的修复方式没有成功
   - 考虑采用完全不同的解决思路（例如：如果之前尝试用 apt-get 安装失败，可以考虑从源码编译、使用不同的包管理器、修改环境变量、或者采用容器化方案等）
   - 避免重复使用已经失败的方法
   - 尝试创新的、不同的解决路径

第三部分：生成修复指令列表
根据错误分析和历史反思，生成一个修复指令列表。要求：
1. 如果发现错误重复出现，必须采用与历史不同的修复策略
2. 生成多个具体的修复指令，按照执行顺序排列
3. 每个指令应该是可以直接执行的 shell 命令
4. 使用非交互式标志（如 -y/--yes）
5. 选择合适的包管理器或工具：
   - 系统包：apt-get/yum/apk + 需要时运行 apt-get update
   - Python: pip/uv/conda；优先使用错误中提示的确切包名
   - Node.js: npm/yarn/pnpm；安装缺失的包或运行时（需要时使用 nvm）
   - 其他：cargo/go/gem/composer；或创建链接/导出变量如果是路径问题
6. 优先选择幂等且安全的命令
7. 如果只需要一个步骤，列表中可以只有一个指令
8. 如果多个步骤可以合并为一个命令（使用 && 连接），可以合并为一个指令
9. 当错误重复出现时，优先考虑替代方案而不是重复相同的方法

输出要求：
- error_analysis: 详细的错误分析文本（如果错误重复出现，必须包含对历史失败的反思和采用新策略的理由）
- repair_commands: 修复指令列表，每个指令都是可以直接执行的 shell 命令字符串，不要包含代码框标记、引号或其他解释性文字

重要：每个修复指令必须是完整的、可以直接执行的 shell 命令。如果错误重复出现，必须采用与历史不同的修复策略。
"""

    def __init__(self, model: BaseChatModel, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)
        
        # 使用结构化输出
        prompt_template = ChatPromptTemplate.from_messages(
            [("system", self.SYS_PROMPT), ("human", "{prompt}")]
        )
        structured_llm = model.with_structured_output(RepairCommandsOutput)
        self.model = prompt_template | structured_llm

    def _init_tools(self):
        """
        初始化文件读取工具。

        Returns:
          List of StructuredTool instances configured for file reading.
        """
        tools = []
        
        # Tool: 读取容器中的文件内容
        read_file_fn = functools.partial(self._read_file_from_container)
        read_file_tool = StructuredTool.from_function(
            func=read_file_fn,
            name="read_file",
            description=READ_FILE_DESCRIPTION,
            args_schema=ReadFileInput,
            response_format="content_and_artifact",
        )
        tools.append(read_file_tool)
        
        return tools

    

    def __call__(self, state: Dict):
        test_command = state.get("test_command", [])
        test_result = state.get("test_result", [])
        test_command_result_history = state.get("test_command_result_history", [])
        
        self._logger.info("分析测试执行结果...")
        
        # 获取最后3轮的历史信息（如果存在）
        previous_rounds_text = ""
        if len(test_command_result_history) > 0:
            # 获取最后3个历史项（包含当前轮，所以取最后3个）
            start_idx = max(0, len(test_command_result_history) - 3)
            end_idx = len(test_command_result_history)
            
            if end_idx > start_idx:
                previous_rounds = test_command_result_history[start_idx:end_idx]
                previous_rounds_parts = []
                
                for idx, history_item in enumerate(previous_rounds):
                    # round_num 是实际在历史中的索引位置（从0开始计数）
                    round_num = start_idx + idx
                    history_command = history_item.get('command', [])
                    history_result = history_item.get('result', [])
                    history_analysis = history_item.get('analysis', '')
                    
                    # 格式化历史命令（可能是列表）
                    command_str = ""
                    if isinstance(history_command, list):
                        command_str = "\n".join([str(cmd) for cmd in history_command])
                    else:
                        command_str = str(history_command)
                    
                    # 格式化历史结果（可能是列表，每个结果包含多个测试命令的结果）
                    result_str_parts = []
                    if isinstance(history_result, list):
                        for res_idx, res in enumerate(history_result):
                            result_str_parts.append(f"""
                            Test {res_idx + 1}:
                              Command: {res.get('command', 'N/A')}
                              Exit Code: {res.get('returncode', 'N/A')}
                              Stdout: {res.get('stdout', '')}
                              Stderr: {res.get('stderr', '')}
                            """)
                    else:
                        result_str_parts.append(f"""
                        Exit Code: {history_result.get('returncode', 'N/A')}
                        Stdout: {history_result.get('stdout', '')}
                        Stderr: {history_result.get('stderr', '')}
                        """)
                    
                    round_text = f"""
                    Round {round_num}:
                    Test Commands:
                    ```
                    {command_str}
                    ```
                    
                    Test Results:
                    {''.join(result_str_parts)}
                    """
                    if history_analysis:
                        round_text += f"  Previous Analysis: {history_analysis}\n"
                    previous_rounds_parts.append(round_text)
                
                if previous_rounds_parts:
                    previous_rounds_text = """
                    TEST COMMAND HISTORY (Last 3 Rounds):
                    """
                    previous_rounds_text += "\n".join(previous_rounds_parts)
        
        # 格式化当前测试结果
        current_test_result_text = ""
        if isinstance(test_result, list) and len(test_result) > 0:
            result_parts = []
            for idx, res in enumerate(test_result):
                result_parts.append(f"""
                Test {idx + 1}:
                  Command: {res.get('command', 'N/A')}
                  Exit Code: {res.get('returncode', 'N/A')}
                  Stdout: {res.get('stdout', '')}
                  Stderr: {res.get('stderr', '')}
                """)
            current_test_result_text = "\n".join(result_parts)
        else:
            current_test_result_text = str(test_result)
        
        # 格式化当前测试命令
        current_test_command_text = ""
        if isinstance(test_command, list):
            current_test_command_text = "\n".join([str(cmd) for cmd in test_command])
        else:
            current_test_command_text = str(test_command)
        
        # 组织查询（显示最新结果，包含最后3轮历史）
        context_query = """
            <context>
            CURRENT TEST COMMAND:
            ```
            """
        context_query += current_test_command_text
        context_query += """
            ```

            CURRENT TEST RESULTS:
            ```
            """
        context_query += current_test_result_text
        context_query += """
            ```
            """
        
        # 如果有历史信息，添加到context中
        if previous_rounds_text:
            context_query += previous_rounds_text
        
        context_query += """
            </context>

            """
        
        # 分析错误并生成修复指令列表
        prompt_text = (
            context_query 
            + "\n请分析上述测试命令执行失败的原因。如果提供了历史轮次信息，请对比当前错误与历史错误。如果发现错误重复出现，请反思之前的修复策略为何无效，并采用完全不同的新策略来解决。最后根据分析结果生成修复指令列表。"
        )
        
        # 使用结构化输出模型
        response = self.model.invoke({"prompt": prompt_text})
        self._logger.debug(f"模型响应: {response}")
        
        # 提取指令列表
        repair_commands = response.repair_commands if hasattr(response, 'repair_commands') else []
        error_analysis_text = response.error_analysis if hasattr(response, 'error_analysis') else ""
        
        self._logger.info(f"错误分析: {error_analysis_text}")
        self._logger.info(f"修复指令列表: {repair_commands}")
        
        # 将修复指令列表转换为字符串列表（根据状态定义，env_repair_command 是 Sequence[str]）
        repair_command_contexts = [
            cmd.strip() for cmd in repair_commands if cmd.strip()
        ]

        # 更新 test_command_result_history 中最后一个条目的 analysis
        test_command_result_history = state.get("test_command_result_history", [])
        if len(test_command_result_history) > 0:
            current_test_history = test_command_result_history[-1].copy()
            current_test_history['analysis'] = error_analysis_text
            test_command_result_history[-1] = current_test_history

        return {
            "env_error_analysis": error_analysis_text,
            "env_repair_command": repair_command_contexts,
            "test_command_result_history": test_command_result_history,
        }

