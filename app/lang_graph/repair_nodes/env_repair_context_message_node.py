import logging
import threading

from app.models.context import Context
from app.lang_graph.states.env_implement_state import EnvImplementState
from app.utils.logger_manager import get_thread_logger

class EnvRepairContextMessageNode:

    def __init__(self, debug_mode: bool):
        self.debug_mode = debug_mode
        self._logger, _file_handler  = get_thread_logger(__name__)

    def __call__(self, state: EnvImplementState):
        env_implement_command = state.get("env_implement_command", "")
        env_implement_result = state.get("env_implement_result", [])
        test_command = state.get("test_command", "")
        test_result = state.get("test_result", [])
        
        # 确保是列表类型
        if not isinstance(env_implement_result, list):
            env_implement_result = []
        if not isinstance(test_result, list):
            test_result = []
        
        # 获取最新的结果（最后一个），或显示所有历史记录
        latest_env_result = env_implement_result[-1] if len(env_implement_result) > 0 else {}
        latest_test_result = test_result[-1] if len(test_result) > 0 else {}

        env_repair_context_query = (
            """
<context>
ENV IMPLEMENT COMMAND:
```
"""
            + str(env_implement_command)
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

        self._logger.debug(
            "Sending environment repair query with state to context provider subgraph:\n%s",
            env_repair_context_query,
        )

        return {
            "env_repair_context_query": env_repair_context_query,
        }
