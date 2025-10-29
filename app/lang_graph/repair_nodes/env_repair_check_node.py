"""节点：检查执行结果，决定是否需要继续循环"""

import logging
import threading
from typing import Dict

from app.utils.logger_manager import get_thread_logger


class EnvRepairCheckNode:
    """ 可否与router合并 """
    """检查 env_implement_result 和 test_result 的状态"""
    
    def __init__(self):
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: Dict):
        env_implement_result = state.get("env_implement_result", [])
        test_result = state.get("test_result", [])
        
        # 确保是列表类型
        if not isinstance(env_implement_result, list):
            env_implement_result = []
        if not isinstance(test_result, list):
            test_result = []
        
        # 检查 env_implement_result 是否成功
        env_success = False
        if len(env_implement_result) > 0:
            last_result = env_implement_result[-1]
            if isinstance(last_result, dict) and 'returncode' in last_result:
                env_success = last_result['returncode'] == 0
        
        # 检查 test_result 是否成功
        test_success = False
        if len(test_result) > 0:
            last_result = test_result[-1]
            if isinstance(last_result, dict) and 'returncode' in last_result:
                test_success = last_result['returncode'] == 0
        elif len(test_result) == 0: 
            # 如果没有 test_result，可能需要先运行 test
            self._logger.info("需要运行测试")
        
        # 判断是否完成
        if env_success and test_success:
            self._logger.info("✅ 环境搭建和测试全部成功！")
            should_continue = False
        elif env_success and not test_success:
            self._logger.info("⚠️ 环境搭建成功，但测试失败")
            should_continue = True
        elif not env_success:
            self._logger.info("❌ 环境搭建失败")
            should_continue = True
        else:
            should_continue = True
        check_state = {
            "should_continue": should_continue,
            "env_success": env_success,
            "test_success": test_success,
        }
        return {
            "check_state": check_state,
        }