#!/bin/bash
#
# Environment Installation Quality Check Script
# Count missing import errors based on pyright static analysis
#

# Do not use set -e, to capture errors and write to result file
set +e

# Configuration parameters
PROJECT_PATH="${1:-/data/project}"  # Project path, default is /data/project
OUTPUT_DIR="${2:-build_output}"    # Output directory, default is build_output

# Error message collection
ERROR_MESSAGES=()

# # Activate virtual environment (if exists)
# # Try common virtual environment paths
VENV_PATHS=("/opt/venv" "$PROJECT_PATH/venv" "$(pwd)/venv" "$HOME/venv")
VENV_ACTIVATED=false

# for venv_path in "${VENV_PATHS[@]}"; do
#     if [ -f "$venv_path/bin/activate" ]; then
#         echo "Activating virtual environment: $venv_path"
#         # shellcheck source=/dev/null
#         source "$venv_path/bin/activate"
#         VENV_ACTIVATED=true
#         break
#     fi
# done

# If virtual environment is not activated, try to read from ~/.bashrc (if exists)
if [ "$VENV_ACTIVATED" = false ] && [ -f "$HOME/.bashrc" ]; then
    # Extract virtual environment path from ~/.bashrc
    venv_line=$(grep -E "source.*bin/activate|\.\s+.*bin/activate" "$HOME/.bashrc" | head -1)
    if [ -n "$venv_line" ]; then
        # Extract path (e.g., extract "/opt/venv" from "source /opt/venv/bin/activate")
        venv_path=$(echo "$venv_line" | sed -E 's/.*(source|\.)\s+([^[:space:]]+)\/bin\/activate.*/\2/')
        if [ -f "$venv_path/bin/activate" ]; then
            echo "Activating virtual environment from ~/.bashrc: $venv_path"
            # shellcheck source=/dev/null
            source "$venv_path/bin/activate"
            VENV_ACTIVATED=true
        fi
    fi
fi

# Verify if Python is available
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "Warning: python or python3 command not found"
    if [ "$VENV_ACTIVATED" = false ]; then
        echo "Hint: Virtual environment may not be activated, try to activate it manually"
    fi
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Set log file path
LOG_FILE="$OUTPUT_DIR/execution.log"

# Output all output (stdout and stderr) to both terminal and log file
# Use tee to output simultaneously, note: content explicitly redirected to file (e.g., > file.json) is not affected
exec > >(tee "$LOG_FILE") 2>&1

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "Error: jq is not installed, please install jq first"
    exit 1
fi

# Install pyright (if not installed)
if ! command -v pyright &> /dev/null; then
    echo "Installing pyright..."
    # Prefer python3, use python if python3 doesn't exist
    INSTALL_ERROR=""
    if command -v python3 &> /dev/null; then
        INSTALL_OUTPUT=$(python3 -m pip install --quiet pyright 2>&1)
        INSTALL_EXIT_CODE=$?
        if [ $INSTALL_EXIT_CODE -ne 0 ]; then
            INSTALL_ERROR="$INSTALL_OUTPUT"
            ERROR_MESSAGES+=("pyright installation failed: $INSTALL_ERROR")
        fi
    elif command -v python &> /dev/null; then
        INSTALL_OUTPUT=$(python -m pip install --quiet pyright 2>&1)
        INSTALL_EXIT_CODE=$?
        if [ $INSTALL_EXIT_CODE -ne 0 ]; then
            INSTALL_ERROR="$INSTALL_OUTPUT"
            ERROR_MESSAGES+=("pyright installation failed: $INSTALL_ERROR")
        fi
    else
        ERROR_MESSAGES+=("Error: python or python3 command not found")
    fi
    
    # If installation failed, still try to continue (pyright may have been installed by other means)
    if [ -n "$INSTALL_ERROR" ]; then
        echo "Warning: pyright installation failed, but continuing to try using installed version"
        echo "$INSTALL_ERROR"
    fi
fi

# Display Python version being used
# Prefer python3, use python if python3 doesn't exist
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: python or python3 command not found"
    exit 1
fi
echo "Using Python: $($PYTHON_CMD --version) at $(which $PYTHON_CMD)"
echo "Checking project path: $PROJECT_PATH"

# Run pyright type checking
echo "Running type checking..."
PYRIGHT_ERROR=""
# Use temporary file to store pyright output, will be deleted after processing
TEMP_PYRIGHT_OUTPUT=$(mktemp)
TEMP_PYRIGHT_STDERR=$(mktemp)

# Determine which pyright command to use (prefer direct command, fallback to python -m)
PYRIGHT_CMD=""
if command -v pyright &> /dev/null; then
    PYRIGHT_CMD="pyright"
    echo "Using pyright command (npm installation)"
elif $PYTHON_CMD -m pyright --version &>/dev/null; then
    PYRIGHT_CMD="$PYTHON_CMD -m pyright"
    echo "Using python -m pyright (pip installation)"
else
    PYRIGHT_ERROR="pyright command not available, cannot perform type checking"
    ERROR_MESSAGES+=("$PYRIGHT_ERROR")
    PYRIGHT_EXIT_CODE=1
fi

# Execute pyright if command is available
if [ -n "$PYRIGHT_CMD" ]; then
    $PYRIGHT_CMD "$PROJECT_PATH" --level error --outputjson > "$TEMP_PYRIGHT_OUTPUT" 2>"$TEMP_PYRIGHT_STDERR"
    PYRIGHT_EXIT_CODE=$?
    
    # Check stderr for errors
    if [ -s "$TEMP_PYRIGHT_STDERR" ]; then
        STDERR_CONTENT=$(cat "$TEMP_PYRIGHT_STDERR")
        if echo "$STDERR_CONTENT" | grep -qi "error\|failed\|not found"; then
            ERROR_MESSAGES+=("pyright execution error: $(echo "$STDERR_CONTENT" | head -3 | tr '\n' ' ')")
        fi
    fi
fi

# Clean up stderr temp file
rm -f "$TEMP_PYRIGHT_STDERR"

# Check if pyright output exists and is valid
if [ ! -f "$TEMP_PYRIGHT_OUTPUT" ] || [ ! -s "$TEMP_PYRIGHT_OUTPUT" ]; then
    ERROR_MESSAGES+=("Error: Unable to get valid pyright output")
    # Create an empty pyright output file
    echo '{"generalDiagnostics":[]}' > "$TEMP_PYRIGHT_OUTPUT"
fi

# Count missing import errors (reportMissingImports)
issue_count=0
missing_imports_issues='{"issues":[]}'

if [ -f "$TEMP_PYRIGHT_OUTPUT" ] && [ -s "$TEMP_PYRIGHT_OUTPUT" ]; then
    # Check if JSON file is valid by trying to parse it
    # First, try to extract JSON from output (in case there are non-JSON lines)
    JSON_CONTENT=$(grep -E '^\s*\{|^\s*\[' "$TEMP_PYRIGHT_OUTPUT" | head -1 || cat "$TEMP_PYRIGHT_OUTPUT")
    
    # Try to validate JSON
    if echo "$JSON_CONTENT" | jq empty 2>/dev/null; then
        # Valid JSON, extract issues
        issue_count=$(echo "$JSON_CONTENT" | jq '[.generalDiagnostics[]? | select(.rule == "reportMissingImports")] | length' 2>/dev/null || echo "0")
        
        # Extract missing import error details
        missing_imports_issues=$(echo "$JSON_CONTENT" | jq '{issues: [.generalDiagnostics[]? | select(.rule == "reportMissingImports")]}' 2>/dev/null || echo '{"issues":[]}')
    else
        # Invalid JSON - check if it's an error message
        OUTPUT_CONTENT=$(cat "$TEMP_PYRIGHT_OUTPUT")
        if echo "$OUTPUT_CONTENT" | grep -qi "error\|failed\|not found"; then
            ERROR_MESSAGES+=("pyright output JSON file is invalid: $(echo "$OUTPUT_CONTENT" | head -5 | tr '\n' ' ')")
        else
            ERROR_MESSAGES+=("pyright output JSON file is invalid")
        fi
        # Create empty result
        missing_imports_issues='{"issues":[]}'
    fi
fi

# If there are error messages, add them to the results
if [ ${#ERROR_MESSAGES[@]} -gt 0 ]; then
    # Add error messages to missing import errors
    ERROR_ISSUES_JSON="[]"
    for error_msg in "${ERROR_MESSAGES[@]}"; do
        ERROR_ISSUE=$(jq -n \
            --arg file "pyright_installation" \
            --arg message "$error_msg" \
            '{file: $file, message: $message, rule: "installation_error"}')
        ERROR_ISSUES_JSON=$(echo "$ERROR_ISSUES_JSON" | jq --argjson issue "$ERROR_ISSUE" '. += [$issue]')
    done
    
    # Merge error messages into missing import errors
    if [ -n "$ERROR_ISSUES_JSON" ] && [ "$ERROR_ISSUES_JSON" != "[]" ]; then
        missing_imports_issues=$(echo "$missing_imports_issues" | jq --argjson errors "$ERROR_ISSUES_JSON" '.issues += $errors')
        issue_count=$((issue_count + ${#ERROR_MESSAGES[@]}))
    fi
fi

# Save missing import error details
echo "$missing_imports_issues" > "$OUTPUT_DIR/missing_imports_issues.json"

# Clean up temporary files
if [ -f "$TEMP_PYRIGHT_OUTPUT" ]; then
    rm -f "$TEMP_PYRIGHT_OUTPUT"
fi

# Output result summary
echo "========================================="
echo "Environment Installation Quality Check Results"
echo "========================================="
echo "Missing import errors count: $issue_count"
echo "Missing import errors details saved to: $OUTPUT_DIR/missing_imports_issues.json"
echo "Execution log saved to: $LOG_FILE"
echo "========================================="

# Return result (smaller issues_count means better quality)
exit 0

