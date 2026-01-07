"""节点：检查执行结果，决定是否需要继续循环"""

from typing import Dict
from xxlimited import Str

from app.utils.logger_manager import get_thread_logger


def router_function(state: Dict, test_mode: Str) -> str:
    _logger, _file_handler = get_thread_logger(__name__)
    """路由器函数：根据 check_state 决定流程"""
    check_state = state.get("check_state", {})

    # 如果 check_state 存在，优先使用 check_state 进行路由
    if check_state:
        env_success = check_state.get("env_success", 0)
        test_success = check_state.get("test_success", 0)

        # 情况1：没有 env_implement_result，首次执行环境命令
        if env_success == 0:
            _logger.info("case1: no env_implement_result, first time to execute env command")
            return "case1"

        # 情况2：环境失败，需要分析错误
        if env_success == -1:
            _logger.info("case2: env_success == -1, env failed, need to analyse error")
            return "case2"

        if test_mode == "generation":
            if env_success == 1 and test_success == 1:  # 成功并全部结束
                _logger.info("all success")
                return "success"
            elif env_success == 1 and (test_success == 2 or test_success == 0):  # 切换level 或 还没执行测试
                _logger.info(f"case3: env_success == 1 and test_success == {test_success}, switch level or not run test (0: not run test, 2: switch level)")
                return "case3"
            elif env_success == 1 and test_success == -1:  # 执行失败
                _logger.info("case4: env_success == 1 and test_success == -1, test failed")
                return "case4"
        else: ## test_mode 为 "pytest"或者 pyright
            # 情况3：环境成功，但还没有运行测试
            if env_success == 1 and test_success == 0:
                _logger.info("case3: env_success == 1 and test_success == 0, env success, but not run test")
                return "case3"

            # 情况4：环境成功但测试失败
            if env_success == 1 and test_success == -1:
                _logger.info("case4: env_success == 1 and test_success == -1, env success, but test failed")
                return "case4"

            # todo 是否会出现，环境首次成功，但是二次运行后失败的情况？

            # 默认情况：都成功
            _logger.info("default case: all success")
            return "success"
    else:
        raise ValueError("check_state is not found")


class EnvRepairCheckNode:
    """可否与router合并"""

    """检查 env_implement_result 和 test_result 的状态"""

    def __init__(self, test_mode: Str):
        self._logger, _file_handler = get_thread_logger(__name__)
        self.test_mode = test_mode

    def __call__(self, state: Dict):
        env_implement_result = state.get("env_implement_result", {})
        test_results = state.get("test_result", [])
        
        # 检查 env_implement_result 是否成功
        # success 0（未运行）1（成功）-1（失败）
        env_success = 0
        test_success = 0
        if len(env_implement_result) > 0:
            if isinstance(env_implement_result, dict) and "returncode" in env_implement_result:
                env_success = 1 if env_implement_result["returncode"] == 0 else -1

        if self.test_mode == "generation":
            if len(test_results) > 0:
                test_success = state.get("test_keep_selecting", -1) # 1 成功并全部结束，-1 执行失败，2 切换level
                # test_success = 1 if test_results["returncode"] == 0 else -1  # generation 模式下，test_result 只是一个命令的结果
            elif len(test_results) == 0:
                # 如果没有 test_result，需要先运行 test
                self._logger.info("Need to run test")
        elif self.test_mode == "CI/CD":
            if len(test_results) > 0:
                test_success_list = []
                for result in test_results:
                    if isinstance(result, dict):
                        returncode = result.get("returncode", 1)
                        # 对于 pyright 模式，还需要检查 issues_count
                        issues_count = result.get("issues_count", None)
                        if issues_count is not None:
                            # issues_count 为 0 表示成功，大于 0 表示失败
                            is_success = returncode == 0 and issues_count == 0
                        else:
                            # 非 pyright 模式，只检查 returncode
                            is_success = returncode == 0
                        test_success_list.append(is_success)
                test_success = 1 if all(test_success_list) else -1 # 确保所有测试都成功
            elif len(test_results) == 0:
                # 如果没有 test_result，需要先运行 test
                self._logger.info("Need to run test")
        elif self.test_mode == "pyright":
            # pyright 模式下，test_result 是一个字典（不是列表）
            if isinstance(test_results, dict) and len(test_results) > 0:
                returncode = test_results.get("returncode", 1)
                issues_count = test_results.get("issues_count", -1)
                # issues_count 为 0 表示成功，大于 0 表示失败
                if issues_count == 0 and returncode == 0:
                    test_success = 1
                elif issues_count > 0 or returncode != 0:
                    test_success = -1
                else:
                    test_success = 0
            elif len(test_results) == 0:
                # 如果没有 test_result，需要先运行 pyright 检查
                pass
        elif self.test_mode == "pytest":
            if isinstance(test_results, dict) and len(test_results) > 0:
                returncode = test_results.get("returncode", 1)
                issues_count = test_results.get("issues_count", -1)
                if issues_count == 0 and returncode == 0: # 成功
                    test_success = 1
                elif issues_count > 0 or returncode != 0: # 失败
                    test_success = -1
                else: # 未运行
                    test_success = 0
            elif len(test_results) == 0:
                # 如果没有 test_result，需要先运行 pytest 检查
                pass
        
        # 判断是否完成
        should_continue = True
        if env_success == 1:
            if test_success == 1:
                should_continue = False
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