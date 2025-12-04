"""节点：执行 pyright 环境质量检查（基于 pyright）"""

import json
import shutil
from pathlib import Path
from typing import Dict

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger
from app.configuration.config import settings

class EnvRepairPyrightExecuteNode:
    """执行环境安装质量检查（使用 pyright）并返回结果"""

    def __init__(self, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)
        # 将pyright 脚本从主机复制到项目目录（主机操作，不在容器内执行）
        source_script = Path(settings.WORKING_DIRECTORY) / "pyright_env_quality_check.sh"
        target_script = self.container.project_path / "pyright_env_quality_check.sh"
        try:
            shutil.copy(source_script, target_script)
            self._logger.info(f"复制 pyright 脚本成功: {source_script} -> {target_script}")
        except Exception as e:
            error_msg = f"复制 pyright 脚本失败: {str(e)}"
            self._logger.error(error_msg)
            raise Exception(error_msg)

    def __call__(self, state: Dict):
        """执行 pyright 环境质量检查"""
        # 使用容器内的工作目录作为项目路径
        project_path = self.container.workdir
        output_dir = "/app/build_output"
        script_path = "/app/pyright_env_quality_check.sh"

        self._logger.info("开始执行环境安装质量检查（pyright 模式）")


        # 给脚本添加执行权限
        chmod_cmd = f"chmod +x {script_path}"
        chmod_result = self.container.execute_command_with_exit_code(chmod_cmd)
        if chmod_result.returncode != 0:
            self._logger.warning(f"添加执行权限失败: {chmod_result.stderr}")

        # 运行脚本
        # 使用 bash -l 启动登录 shell，确保加载 ~/.bashrc（包含虚拟环境激活）
        self._logger.info(f"执行环境质量检查脚本: {script_path}")
        run_script_cmd = f"bash -l -c '{script_path} {project_path} {output_dir}'"
        script_result = self.container.execute_command_with_exit_code(run_script_cmd)


        # 产出3个文件 missing_imports_issues.json  pyright_output.json  results.json
        # 读取结果文件
        read_results_cmd = f"cat {output_dir}/results.json 2>/dev/null || echo '{{}}'"
        results_output = self.container.execute_command_with_exit_code(read_results_cmd)
        # 读取缺失导入错误详情文件
        read_missing_imports_issues_cmd = f"cat {output_dir}/missing_imports_issues.json 2>/dev/null || echo '{{}}'"
        missing_imports_issues_output = self.container.execute_command_with_exit_code(read_missing_imports_issues_cmd)

        # 解析结果
        try:
            if results_output.returncode == 0 and results_output.stdout.strip():
                results_data = json.loads(results_output.stdout)
                issues_count = results_data.get("issues_count", -1)
                pyright_data = results_data.get("pyright", {})
            else:
                # 如果无法读取结果文件，尝试从脚本输出中提取信息
                self._logger.error("无法读取结果文件")
                raise Exception("无法读取结果文件")
            
            if missing_imports_issues_output.returncode == 0 and missing_imports_issues_output.stdout.strip():
                missing_imports_issues_data = json.loads(missing_imports_issues_output.stdout)
                missing_imports_issues = missing_imports_issues_data.get("issues", [])
            else:
                self._logger.error("无法读取缺失导入错误详情文件")
                raise Exception("无法读取缺失导入错误详情文件")

            self._logger.info(f"检测到 {issues_count} 个缺失导入错误")

            # 构建结果字典：更新test_result结果，不追加
            test_result_dict = {
                "command": "pyright_check",
                "returncode": 0 if issues_count == 0 else 1,  # 0 个错误表示成功 
                "env_issues": missing_imports_issues,
                "issues_count": issues_count,
                "pyright_data": pyright_data,  # 包含完整的 pyright 输出
            }

            # 更新历史记录
            test_command_result_history = state.get("test_command_result_history", []) + [
                {
                    "result": test_result_dict,
                }
            ]
            return {
                "test_result": test_result_dict,
                "test_command_result_history": test_command_result_history,
            }
        except Exception as e:
            self._logger.error(f"执行 pyright 环境质量检查失败: {e}")
            return {
                "test_result": {},
                "test_command_result_history": {},
            }
