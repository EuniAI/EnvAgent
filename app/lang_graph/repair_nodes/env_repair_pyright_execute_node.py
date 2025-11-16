"""节点：执行 pyright 环境质量检查（基于 pyright）"""

import json
from typing import Dict

from app.container.base_container import BaseContainer
from app.utils.logger_manager import get_thread_logger


# env_quality_check.sh 脚本内容
ENV_QUALITY_CHECK_SCRIPT = """#!/bin/bash
#
# 环境安装质量监测脚本
# 基于 pyright 静态分析统计缺失导入错误数量
#

set -e

# 配置参数
PROJECT_PATH="${1:-/data/project}"  # 项目路径，默认为 /data/project
OUTPUT_DIR="${2:-build_output}"    # 输出目录，默认为 build_output

# 创建输出目录
mkdir -p "$OUTPUT_DIR"

# 检查 jq 是否安装
if ! command -v jq &> /dev/null; then
    echo "错误: jq 未安装，请先安装 jq"
    exit 1
fi

# 安装 pyright（如果未安装）
if ! command -v pyright &> /dev/null; then
    echo "正在安装 pyright..."
    python -m pip install --quiet pyright
fi

# 显示使用的 Python 版本
echo "使用 Python: $(python --version) 位于 $(which python)"
echo "检查项目路径: $PROJECT_PATH"

# 运行 pyright 类型检查
echo "正在运行类型检查..."
python -m pyright "$PROJECT_PATH" --level error --outputjson > "$OUTPUT_DIR/pyright_output.json" || true

# 检查 pyright 输出是否存在且有效
if [ ! -f "$OUTPUT_DIR/pyright_output.json" ]; then
    echo "错误: 无法获取有效的 pyright 输出"
    exit 1
fi

# 统计缺失导入错误数量（reportMissingImports）
issue_count=$(jq '[.generalDiagnostics[] | select(.rule == "reportMissingImports")] | length' \\
    "$OUTPUT_DIR/pyright_output.json")

# 创建结果 JSON
results_json=$(jq -n \\
    --arg issues "$issue_count" \\
    --argfile pyright "$OUTPUT_DIR/pyright_output.json" \\
    '{issues_count: ($issues|tonumber), pyright: $pyright}')

# 保存结果
echo "$results_json" > "$OUTPUT_DIR/results.json"

# 输出结果摘要
echo "========================================="
echo "环境安装质量监测结果"
echo "========================================="
echo "缺失导入错误数量: $issue_count"
echo "结果已保存到: $OUTPUT_DIR/results.json"
echo "========================================="

# 返回结果（issues_count 越小，质量越好）
exit 0
"""


class EnvRepairPyrightExecuteNode:
    """执行环境安装质量检查（使用 pyright）并返回结果"""

    def __init__(self, container: BaseContainer):
        self.container = container
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: Dict):
        """执行 pyright 环境质量检查"""
        # 使用容器内的工作目录作为项目路径
        project_path = self.container.workdir
        output_dir = "build_output"
        script_path = "env_quality_check.sh"

        self._logger.info("开始执行环境安装质量检查（pyright 模式）")

        # 将脚本内容写入容器内的文件
        # 使用 heredoc 方式写入，单引号标记 'ENDOFSCRIPT' 防止变量展开
        write_script_cmd = f'''
            cat > {script_path} << 'ENDOFSCRIPT'
            {ENV_QUALITY_CHECK_SCRIPT}ENDOFSCRIPT
        '''
        write_result = self.container.execute_command_with_exit_code(write_script_cmd)
        if write_result.returncode != 0:
            self._logger.error(f"写入脚本文件失败: {write_result.stderr}")
            return {
                "test_result": [{
                    "command": "pyright_check",
                    "returncode": 1,
                    "stdout": write_result.stdout,
                    "stderr": write_result.stderr or "无法写入脚本文件",
                    "issues_count": -1,
                }],
            }

        # 给脚本添加执行权限
        chmod_cmd = f"chmod +x {script_path}"
        chmod_result = self.container.execute_command_with_exit_code(chmod_cmd)
        if chmod_result.returncode != 0:
            self._logger.warning(f"添加执行权限失败: {chmod_result.stderr}")

        # 运行脚本
        self._logger.info(f"执行环境质量检查脚本: {script_path}")
        run_script_cmd = f"bash {script_path} {project_path} {output_dir}"
        script_result = self.container.execute_command_with_exit_code(run_script_cmd)

        # 读取结果文件
        read_results_cmd = f"cat {output_dir}/results.json 2>/dev/null || echo '{{}}'"
        results_output = self.container.execute_command_with_exit_code(read_results_cmd)

        # 解析结果
        try:
            if results_output.returncode == 0 and results_output.stdout.strip():
                results_data = json.loads(results_output.stdout)
                issues_count = results_data.get("issues_count", -1)
                pyright_data = results_data.get("pyright", {})
            else:
                # 如果无法读取结果文件，尝试从脚本输出中提取信息
                self._logger.warning("无法读取结果文件，尝试从脚本输出中提取信息")
                issues_count = -1
                pyright_data = {}
                # 尝试从脚本输出中提取 issues_count
                if "缺失导入错误数量:" in script_result.stdout:
                    try:
                        for line in script_result.stdout.split("\n"):
                            if "缺失导入错误数量:" in line:
                                issues_count_str = line.split(":")[-1].strip()
                                issues_count = int(issues_count_str)
                                break
                    except (ValueError, IndexError):
                        pass

            self._logger.info(f"检测到 {issues_count} 个缺失导入错误")

            # 构建结果字典
            test_result_dict = {
                "command": "pyright_check",
                "returncode": 0 if issues_count == 0 else 1,  # 0 个错误表示成功
                "stdout": script_result.stdout,
                "stderr": script_result.stderr or "",
                "issues_count": issues_count,
                "pyright_data": pyright_data,  # 包含完整的 pyright 输出
            }

            # 获取现有的 test_result 列表
            existing_test_results = state.get("test_result", [])
            if not isinstance(existing_test_results, list):
                existing_test_results = []

            # 追加新结果
            new_test_results = existing_test_results + [test_result_dict]

            # 更新历史记录
            test_command_result_history = state.get("test_command_result_history", []) + [
                {
                    "command": "pyright_check",
                    "result": [test_result_dict],
                }
            ]

            return {
                "test_result": new_test_results,
                "test_command_result_history": test_command_result_history,
            }

        except json.JSONDecodeError as e:
            self._logger.error(f"解析结果 JSON 失败: {e}")
            return {
                "test_result": [{
                    "command": "pyright_check",
                    "returncode": 1,
                    "stdout": script_result.stdout,
                    "stderr": f"JSON 解析错误: {str(e)}",
                    "issues_count": -1,
                }],
            }

