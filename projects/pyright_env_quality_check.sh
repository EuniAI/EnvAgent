#!/bin/bash
#
# Environment Installation Quality Check Script
# Run pyright static analysis
#

# Do not use set -e, to capture errors and write to result file
set +e

# Configuration parameters
PROJECT_PATH="${1:-/data/project}"  # Project path, default is /data/project
OUTPUT_DIR="${2:-build_output}"    # Output directory, default is build_output

# Check if we're already in a virtual environment
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Virtual environment already active: $VIRTUAL_ENV"
    VENV_ACTIVATED=true
else
    VENV_ACTIVATED=false
    # Try common virtual environment paths
    VENV_PATHS=("/opt/venv" "$PROJECT_PATH/venv" "$(pwd)/venv" "$HOME/venv")
    
    # Try to activate existing virtual environment
    for venv_path in "${VENV_PATHS[@]}"; do
        if [ -f "$venv_path/bin/activate" ]; then
            echo "Activating virtual environment: $venv_path"
            # shellcheck source=/dev/null
            source "$venv_path/bin/activate"
            VENV_ACTIVATED=true
            break
        fi
    done
    
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

# Determine Python command to use
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
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Using virtual environment: $VIRTUAL_ENV"
fi
echo "Checking project path: $PROJECT_PATH"

# Install pyright using Python pip (if not installed or not available as module)
if ! $PYTHON_CMD -m pyright --version &> /dev/null; then
    echo "Installing pyright using Python pip..."
    
    # Try to install pyright
    # If in virtual environment, install normally
    # If not in virtual environment, try --user flag first, then --break-system-packages as last resort
    if [ "$VENV_ACTIVATED" = true ] || [ -n "$VIRTUAL_ENV" ]; then
        # In virtual environment, install normally
        $PYTHON_CMD -m pip install --quiet pyright
        INSTALL_RESULT=$?
    else
        # Not in virtual environment, try --user first
        echo "Not in virtual environment, trying --user installation..."
        $PYTHON_CMD -m pip install --quiet --user pyright
        INSTALL_RESULT=$?
        
        # If --user fails, try creating a temporary virtual environment
        if [ $INSTALL_RESULT -ne 0 ]; then
            echo "User installation failed, creating temporary virtual environment..."
            TEMP_VENV="$OUTPUT_DIR/.venv_pyright"
            if [ ! -d "$TEMP_VENV" ]; then
                $PYTHON_CMD -m venv "$TEMP_VENV"
                if [ $? -eq 0 ]; then
                    echo "Activating temporary virtual environment: $TEMP_VENV"
                    # shellcheck source=/dev/null
                    source "$TEMP_VENV/bin/activate"
                    $PYTHON_CMD -m pip install --quiet pyright
                    INSTALL_RESULT=$?
                    # Update PYTHON_CMD to use venv python
                    PYTHON_CMD="$(which python3 || which python)"
                else
                    echo "Failed to create temporary virtual environment"
                    INSTALL_RESULT=1
                fi
            else
                # Virtual environment exists, just activate it
                echo "Activating existing temporary virtual environment: $TEMP_VENV"
                # shellcheck source=/dev/null
                source "$TEMP_VENV/bin/activate"
                $PYTHON_CMD -m pip install --quiet pyright
                INSTALL_RESULT=$?
                # Update PYTHON_CMD to use venv python
                PYTHON_CMD="$(which python3 || which python)"
            fi
        fi
    fi
    
    if [ $INSTALL_RESULT -ne 0 ]; then
        echo "Error: Failed to install pyright"
        exit 1
    fi
    echo "Pyright installed successfully"
fi

# Verify pyright is available as Python module
if ! $PYTHON_CMD -m pyright --version &> /dev/null; then
    echo "Error: pyright is not available as a Python module"
    exit 1
fi

# Run pyright type checking using Python module
echo "Running type checking..."
$PYTHON_CMD -m pyright "$PROJECT_PATH" --level error --outputjson

