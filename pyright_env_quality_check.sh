#!/bin/bash
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
issue_count=$(jq '[.generalDiagnostics[] | select(.rule == "reportMissingImports")] | length' \
    "$OUTPUT_DIR/pyright_output.json")

# 创建结果 JSON
results_json=$(jq -n \
    --arg issues "$issue_count" \
    --argfile pyright "$OUTPUT_DIR/pyright_output.json" \
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

