"""节点：分析 env_implement_result 中的错误"""

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


class EnvRepairAnalyseNode:
    """分析环境命令执行结果中的错误并生成修复命令"""
    
    SYS_PROMPT = """\
你是一个环境修复分析专家。你的任务是分析环境命令执行的结果，识别错误原因，并生成具体的修复指令列表。

输入包含：
- ENV IMPLEMENT COMMAND: 已执行的环境命令
- ENV IMPLEMENT OUTPUT: 命令的输出结果（包含错误信息）
- TEST COMMAND: 需要运行的测试命令（如果有）

你的任务分为两部分：

第一部分：错误分析
1. 仔细分析 ENV IMPLEMENT OUTPUT 中的错误信息
2. 识别根本原因（如：模块未找到、命令不存在、缺少共享库、版本冲突等）
3. 分析为什么当前命令无法完成环境搭建
4. 提供详细的错误分析总结

第二部分：生成修复指令列表
根据错误分析，生成一个修复指令列表。要求：
1. 生成多个具体的修复指令，按照执行顺序排列
2. 每个指令应该是可以直接执行的 shell 命令
3. 使用非交互式标志（如 -y/--yes）
4. 选择合适的包管理器或工具：
   - 系统包：apt-get/yum/apk + 需要时运行 apt-get update
   - Python: pip/uv/conda；优先使用错误中提示的确切包名
   - Node.js: npm/yarn/pnpm；安装缺失的包或运行时（需要时使用 nvm）
   - 其他：cargo/go/gem/composer；或创建链接/导出变量如果是路径问题
5. 优先选择幂等且安全的命令
6. 如果只需要一个步骤，列表中可以只有一个指令
7. 如果多个步骤可以合并为一个命令（使用 && 连接），可以合并为一个指令

输出要求：
- error_analysis: 详细的错误分析文本
- repair_commands: 修复指令列表，每个指令都是可以直接执行的 shell 命令字符串，不要包含代码框标记、引号或其他解释性文字

重要：每个修复指令必须是完整的、可以直接执行的 shell 命令。
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

    def _read_file_from_container(self, file_path: str, n_lines: int = 1000) -> str:
        """从容器中读取文件内容，支持绝对路径和相对路径"""
        self._logger.info(f"从容器中读取文件: {file_path}")
        if not self.container or not self.container.is_running():
            return "容器未运行，无法读取文件。"
        
        try:
            # 使用 head 命令限制行数，然后使用 cat 读取
            # 先检查文件是否存在
            check_command = f'test -f "{file_path}" && echo "exists" || echo "not_exists"'
            check_result = self.container.execute_command(check_command).strip()
            
            if "not_exists" in check_result:
                return f"文件 {file_path} 不存在。"
            
            # 读取文件内容（限制行数）
            read_command = f'head -n {n_lines} "{file_path}"'
            content = self.container.execute_command(read_command)
            
            if not content:
                return f"文件 {file_path} 为空。"
            
            # 添加行号
            return pre_append_line_numbers(content, 1)
        except Exception as e:
            self._logger.error(f"读取容器文件 {file_path} 时出错: {str(e)}")
            return f"读取文件 {file_path} 时出错: {str(e)}"

    def __call__(self, state: Dict):
        env_implement_command = state.get("env_implement_command", "")
        env_implement_result = state.get("env_implement_result", [])
        test_command = state.get("test_command", "")
        test_result = state.get("test_result", [])
        str_env_implement_command = self._read_file_from_container(file_path= env_implement_command.split("bash ")[-1])
        
        # 确保是列表类型
        if not isinstance(env_implement_result, list):
            env_implement_result = []
        if not isinstance(test_result, list):
            test_result = []
        
        # 获取最新的结果（最后一个）
        latest_env_result = env_implement_result[-1] if len(env_implement_result) > 0 else {}
        latest_test_result = test_result[-1] if len(test_result) > 0 else {}
        
        self._logger.info("分析环境执行结果...")
        
        # 组织查询（显示最新结果，但也可以考虑显示所有历史）
        context_query = (
            """
            <context>
            ENV IMPLEMENT COMMAND:
            ```
            """
            + str_env_implement_command
            + """
            ```

            ENV IMPLEMENT OUTPUT (Latest):
            ```
            """
            + str(latest_env_result)
            + """
            ```

            TEST COMMAND:
            ```
            """
            + str(test_command)
            + """
            ```

            TEST OUTPUT (Latest):
            ```
            """
            + str(latest_test_result)
            + """
            ```
            </context>

            """
        )
        
        # 分析错误并生成修复指令列表
        prompt_text = (
            context_query 
            + "\n请分析上述环境命令执行失败的原因，并根据分析结果生成修复指令列表。"
        )
        
        # 使用结构化输出模型
        response = self.model.invoke({"prompt": prompt_text})
        self._logger.debug(f"模型响应: {response}")
        
        # 提取指令列表
        repair_commands = response.repair_commands if hasattr(response, 'repair_commands') else []
        error_analysis_text = response.error_analysis if hasattr(response, 'error_analysis') else ""
        
        self._logger.info(f"错误分析: {error_analysis_text}")
        self._logger.info(f"修复指令列表: {repair_commands}")
        
        # 将修复指令列表转换为 Context 格式（根据状态定义）
        from app.models.context import Context
        repair_command_contexts = [
            Context(
                relative_path="",
                start_line=0,
                end_line=0,
                content=cmd
            )
            for cmd in repair_commands
        ]
        
        return {
            "error_analysis": error_analysis_text,
            "env_repair_command": repair_command_contexts,
        }

