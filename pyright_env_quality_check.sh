#!/bin/bash
#
# 环境安装质量监测脚本
# 基于 pyright 静态分析统计缺失导入错误数量
#

set -e

# 配置参数
PROJECT_PATH="${1:-/data/project}"  # 项目路径，默认为 /data/project
OUTPUT_DIR="${2:-build_output}"    # 输出目录，默认为 build_output

# 激活虚拟环境（如果存在）
# 尝试常见的虚拟环境路径
VENV_PATHS=("/opt/venv" "$PROJECT_PATH/venv" "$(pwd)/venv" "$HOME/venv")
VENV_ACTIVATED=false

for venv_path in "${VENV_PATHS[@]}"; do
    if [ -f "$venv_path/bin/activate" ]; then
        echo "激活虚拟环境: $venv_path"
        # shellcheck source=/dev/null
        source "$venv_path/bin/activate"
        VENV_ACTIVATED=true
        break
    fi
done

# 如果虚拟环境未激活，尝试从 ~/.bashrc 中读取（如果存在）
if [ "$VENV_ACTIVATED" = false ] && [ -f "$HOME/.bashrc" ]; then
    # 从 ~/.bashrc 中提取虚拟环境路径
    venv_line=$(grep -E "source.*bin/activate|\.\s+.*bin/activate" "$HOME/.bashrc" | head -1)
    if [ -n "$venv_line" ]; then
        # 提取路径（例如：从 "source /opt/venv/bin/activate" 提取 "/opt/venv"）
        venv_path=$(echo "$venv_line" | sed -E 's/.*(source|\.)\s+([^[:space:]]+)\/bin\/activate.*/\2/')
        if [ -f "$venv_path/bin/activate" ]; then
            echo "从 ~/.bashrc 激活虚拟环境: $venv_path"
            # shellcheck source=/dev/null
            source "$venv_path/bin/activate"
            VENV_ACTIVATED=true
        fi
    fi
fi

# 验证 Python 是否可用
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "警告: 未找到 python 或 python3 命令"
    if [ "$VENV_ACTIVATED" = false ]; then
        echo "提示: 虚拟环境可能未激活，尝试手动激活虚拟环境"
    fi
fi

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
    # 优先使用 python3，如果不存在则使用 python
    if command -v python3 &> /dev/null; then
        python3 -m pip install --quiet pyright
    elif command -v python &> /dev/null; then
        python -m pip install --quiet pyright
    else
        echo "错误: 未找到 python 或 python3 命令"
        exit 1
    fi
fi

# 显示使用的 Python 版本
# 优先使用 python3，如果不存在则使用 python
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "错误: 未找到 python 或 python3 命令"
    exit 1
fi
echo "使用 Python: $($PYTHON_CMD --version) 位于 $(which $PYTHON_CMD)"
echo "检查项目路径: $PROJECT_PATH"

# 运行 pyright 类型检查
echo "正在运行类型检查..."
$PYTHON_CMD -m pyright "$PROJECT_PATH" --level error --outputjson > "$OUTPUT_DIR/pyright_output.json" || true

# 检查 pyright 输出是否存在且有效
if [ ! -f "$OUTPUT_DIR/pyright_output.json" ]; then
    echo "错误: 无法获取有效的 pyright 输出"
    exit 1
fi

# 统计缺失导入错误数量（reportMissingImports）
issue_count=$(jq '[.generalDiagnostics[] | select(.rule == "reportMissingImports")] | length' \
    "$OUTPUT_DIR/pyright_output.json")

# 提取缺失导入错误详情
missing_imports_issues=$(jq '{issues: [.generalDiagnostics[] | select(.rule == "reportMissingImports")]}' \
    "$OUTPUT_DIR/pyright_output.json")

# 保存缺失导入错误详情
echo "$missing_imports_issues" > "$OUTPUT_DIR/missing_imports_issues.json"

# 创建结果 JSON（使用 --slurpfile 替代已弃用的 --argfile）
results_json=$(jq -n \
    --arg issues "$issue_count" \
    --slurpfile pyright "$OUTPUT_DIR/pyright_output.json" \
    '{issues_count: ($issues|tonumber), pyright: $pyright[0]}')

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

