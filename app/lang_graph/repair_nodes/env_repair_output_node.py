"""节点：根据分析结果生成单步修复命令"""

import logging
import threading
from typing import Dict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage

from app.utils.logger_manager import get_thread_logger


class EnvRepairOutputNode:
    """根据分析结果生成单步修复命令"""
    
    SYS_PROMPT = """\
你是一个环境修复命令生成专家。你的任务是生成单一的下一条 shell 命令来修复环境问题。

输入包含：
- ENV IMPLEMENT COMMAND: 已执行的环境命令
- ENV IMPLEMENT OUTPUT: 命令的输出结果（包含错误信息）
- 错误分析：对错误的详细分析

你的任务：
1. 根据错误分析，确定最合适的修复方案
2. 生成 ONE 条修复命令，这是最可能修复环境问题的命令
3. 使用非交互式标志（如 -y/--yes）
4. 选择合适的包管理器或工具：
   - 系统包：apt-get/yum/apk + 需要时运行 apt-get update
   - Python: pip/uv/conda；优先使用错误中提示的确切包名
   - Node.js: npm/yarn/pnpm；安装缺失的包或运行时（需要时使用 nvm）
   - 其他：cargo/go/gem/composer；或创建链接/导出变量如果是路径问题
5. 优先选择幂等且安全的命令；如需要可将子步骤用 && 连接
6. 只输出命令行。不要解释，不要代码框，不要引号。

返回格式：单行的 shell 命令
"""

    def __init__(self, model: BaseChatModel):
        self.model = model
        self.system_prompt = SystemMessage(self.SYS_PROMPT)
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: Dict):
        env_implement_result = state.get("env_implement_result", [])
        error_analysis = state.get("error_analysis", "")
        
        # 确保是列表类型
        if not isinstance(env_implement_result, list):
            env_implement_result = []
        
        # 获取最新的结果（最后一个）
        latest_env_result = env_implement_result[-1] if len(env_implement_result) > 0 else {}
        
        self._logger.info("生成修复命令...")
        
        # 组合查询内容
        query = f"""\
ENV IMPLEMENT OUTPUT (Latest):
```
{latest_env_result}
```

错误分析:
```
{error_analysis}
```

请根据错误分析生成一条修复命令。
"""
        
        message_history = [self.system_prompt, HumanMessage(query)]
        response = self.model.invoke(message_history)
        
        repair_command = response.content.strip() if hasattr(response, 'content') else str(response).strip()
        # 移除可能的代码框标记
        repair_command = repair_command.replace("```bash", "").replace("```", "").strip()
        repair_command = repair_command.replace('"', '').replace("'", "").strip()
        
        self._logger.info(f"生成的修复命令: {repair_command}")
        
        return {
            "env_repair_command": repair_command,
        }

