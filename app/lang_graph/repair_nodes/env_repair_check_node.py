"""节点：检查执行结果，决定是否需要继续循环"""

from typing import Dict

from app.utils.logger_manager import get_thread_logger


class EnvRepairCheckNode:
    """可否与router合并"""

    """检查 env_implement_result 和 test_result 的状态"""

    def __init__(self, test_mode: str):
        self._logger, _file_handler = get_thread_logger(__name__)
        self.test_mode = test_mode

    def __call__(self, state: Dict):
        env_implement_result = state.get("env_implement_result", {})
        test_results = state.get("test_result", [])
        # 检查 env_implement_result 是否成功
        env_success = False
        test_success = False
        if len(env_implement_result) > 0:
            if isinstance(env_implement_result, dict) and "returncode" in env_implement_result:
                env_success = env_implement_result["returncode"] == 0

        if self.test_mode == "generation":
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
                test_success = all(test_success_list)  # 确保所有测试都成功
            elif len(test_results) == 0:
                # 如果没有 test_result，可能需要先运行 test
                self._logger.info("需要运行测试")
        elif self.test_mode == "pyright":
            pass
            



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