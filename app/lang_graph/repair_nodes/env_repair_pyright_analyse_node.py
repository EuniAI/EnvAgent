"""节点：分析 pyright 环境质量检查结果中的错误"""

import functools
from typing import Dict, List

from langchain.prompts import ChatPromptTemplate
from langchain.tools import StructuredTool
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger


class ReadFileInput(BaseModel):
    file_path: str = Field(
        description="文件的路径，可以是绝对路径（如 /app/prometheus_setup.sh）或相对路径"
    )


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


class EnvRepairPyrightAnalyseNode:
    """分析 pyright 环境质量检查结果中的错误并生成修复命令"""

    SYS_PROMPT = """\
你是一个环境修复分析专家。你的任务是分析 pyright 环境质量检查的历史结果，识别缺失导入错误的原因，并生成具体的修复指令列表。

输入包含：
- PYRIGHT CHECK HISTORY: 最后3轮的 pyright 检查历史和结果
- CURRENT PYRIGHT RESULTS: 当前最新的 pyright 检查结果

你的任务分为三部分：

第一部分：错误分析
1. 仔细分析当前 pyright 检查结果中的缺失导入错误（env_issues）
2. 识别每个缺失导入错误的根本原因（如：Python 包未安装、包名错误、版本不匹配、路径问题等）
3. 分析为什么这些导入会失败
4. 提供详细的错误分析总结，包括：
   - 缺失的模块/包列表
   - 每个缺失模块可能对应的包名
   - 安装这些包可能需要的包管理器

第二部分：历史反思
如果提供了 PYRIGHT CHECK HISTORY（最后3轮历史），你需要：
1. 对比当前错误与历史轮次中的错误
2. 判断当前错误是否与历史错误相同或相似（例如：相同的模块一直缺失）
3. 如果错误一直出现（重复了多轮），说明之前的修复策略可能无效
4. 在这种情况下，你需要：
   - 反思为什么之前的修复方式没有成功（例如：包名错误、需要不同的包管理器、需要系统级依赖等）
   - 考虑采用完全不同的解决思路（例如：如果之前尝试用 pip 安装失败，可以考虑用 apt-get 安装系统包、使用不同的包名、从源码安装、修改 PYTHONPATH 等）
   - 避免重复使用已经失败的方法
   - 尝试创新的、不同的解决路径

第三部分：生成修复指令列表
根据错误分析和历史反思，生成一个修复指令列表。要求：
1. 如果发现错误重复出现，必须采用与历史不同的修复策略
2. 生成多个具体的修复指令，按照执行顺序排列
3. 每个指令应该是可以直接执行的 shell 命令
4. 使用非交互式标志（如 -y/--yes）
5. 选择合适的包管理器或工具：
   - Python 包：pip/uv/conda；优先使用错误中提示的确切包名
   - 系统包（如果 Python 包需要系统依赖）：apt-get/yum/apk + 需要时运行 apt-get update
   - 如果包名不确定，可以尝试常见的变体（如 python3-xxx, python-xxx）
6. 优先选择幂等且安全的命令
7. 如果只需要一个步骤，列表中可以只有一个指令
8. 如果多个步骤可以合并为一个命令（使用 && 连接），可以合并为一个指令
9. 当错误重复出现时，优先考虑替代方案而不是重复相同的方法
10. 对于缺失的导入，优先安装对应的 Python 包；如果失败，考虑安装系统包或设置环境变量

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


    def __call__(self, state: Dict):
        test_result = state.get("test_result", {})
        test_command_result_history = state.get("test_command_result_history", [])

        self._logger.info("分析 pyright 环境质量检查结果...")

        # 获取最后3轮的历史信息（如果存在）
        previous_rounds_text = ""
        if len(test_command_result_history) > 0:
            # 获取最后3个历史项（不包含当前轮），当前轮是最后一个，所以从倒数第4个开始
            start_idx = max(0, len(test_command_result_history) - 4)
            end_idx = len(test_command_result_history) - 1

            if end_idx > start_idx:
                previous_rounds = test_command_result_history[start_idx:end_idx]
                previous_rounds_parts = []

                for idx, history_item in enumerate(previous_rounds):
                    # round_num 是实际在历史中的索引位置（从0开始计数）
                    round_num = start_idx + idx
                    history_result = history_item.get("result", []).get("env_issues", []) #'env_issues' : 'file','message'
                    history_analysis = history_item.get("analysis", "")

                    # 格式化历史结果（pyright 检查结果）
                    
                    if isinstance(history_result, list) and len(history_result) > 0:
                        result_str_parts = []
                        for issue in history_result:
                            file = issue.get("file", "")
                            result = issue.get("message", "")
                            result_str_parts.append(f"""
                                File: {file}
                                result: {result}
                                """)
                    else:
                        raise ValueError("pytest_history_result 不是列表")

                    previous_rounds_parts.append(f"""
                    Round {round_num}:
                    {"".join(result_str_parts)}
                    Previous Analysis: {history_analysis}
                    """)

                if len(previous_rounds_parts) > 0:
                    previous_rounds_text = """
                    PYRIGHT CHECK HISTORY (Last 3 Rounds):
                    """
                    previous_rounds_text += "\n".join(previous_rounds_parts)

        # 格式化当前 pyright 检查结果
        current_pyright_result_text = ""
        if isinstance(test_result, dict):
            test_result = test_result.get("env_issues", [])
            result_str_parts = []
            for issue in test_result:
                file = issue.get("file", "")
                result = issue.get("message", "")
                result_str_parts.append(f"""
                    File: {file}
                    result: {result}
                    """)
            current_pyright_result_text = "\n".join(result_str_parts)
        else:
            raise ValueError("pytest current test_result 不是字典")

        # 组织查询（显示最新结果，包含最后3轮历史）
        context_query = """
            <context>
            CURRENT PYRIGHT CHECK RESULTS:
            ```
            """
        context_query += current_pyright_result_text
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
            + "\n请分析上述 pyright 环境质量检查失败的原因。重点关注缺失导入错误（Missing Import Issues）。如果提供了历史轮次信息，请对比当前错误与历史错误。如果发现错误重复出现，请反思之前的修复策略为何无效，并采用完全不同的新策略来解决。最后根据分析结果生成修复指令列表。"
        )

        # 使用结构化输出模型
        response = self.model.invoke({"prompt": prompt_text})
        self._logger.debug(f"模型响应: {response}")

        # 提取指令列表
        repair_commands = response.repair_commands if hasattr(response, "repair_commands") else []
        error_analysis_text = response.error_analysis if hasattr(response, "error_analysis") else ""

        self._logger.info(f"错误分析: {error_analysis_text}")
        self._logger.info(f"修复指令列表: {repair_commands}")

        # 将修复指令列表转换为字符串列表（根据状态定义，env_repair_command 是 Sequence[str]）
        repair_command_contexts = [cmd.strip() for cmd in repair_commands if cmd.strip()]

        # 更新 test_command_result_history 中最后一个条目的 analysis
        test_command_result_history = state.get("test_command_result_history", [])
        if len(test_command_result_history) > 0:
            current_test_history = test_command_result_history[-1].copy()
            current_test_history["analysis"] = error_analysis_text
            test_command_result_history[-1] = current_test_history

        return {
            "env_error_analysis": error_analysis_text,
            "env_repair_command": repair_command_contexts,
            "test_command_result_history": test_command_result_history,
            "test_result": {},  # 清空test_result，因为当前轮次已经执行完毕，需要重新执行

        }

