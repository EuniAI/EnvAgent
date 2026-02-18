#!/bin/bash
#
# Environment Installation Quality Check Script
# Run pytest collect-only to check for missing imports
#

set +e

PROJECT_PATH="${1:-/data/project}"

# Activate virtual environment if not already active
if [ -z "$VIRTUAL_ENV" ]; then
    # Try common virtual environment paths
    for venv_path in "/opt/venv" "$PROJECT_PATH/.venv" "$PROJECT_PATH/venv" "$HOME/venv"; do
        if [ -f "$venv_path/bin/activate" ]; then
            source "$venv_path/bin/activate"
            break
        fi
    done
    
    # Try reading from ~/.bashrc if still not activated
    if [ -z "$VIRTUAL_ENV" ] && [ -f "$HOME/.bashrc" ]; then
        venv_line=$(grep -E "source.*bin/activate|\.\s+.*bin/activate" "$HOME/.bashrc" | head -1)
        if [ -n "$venv_line" ]; then
            venv_path=$(echo "$venv_line" | sed -E 's/.*(source|\.)\s+([^[:space:]]+)\/bin\/activate.*/\2/')
            [ -f "$venv_path/bin/activate" ] && source "$venv_path/bin/activate"
        fi
    fi
fi

# Change to project directory
cd "$PROJECT_PATH" || exit 1

# Determine Python command (prefer python3)
PYTHON_CMD=$(command -v python3 || command -v python)
if [ -z "$PYTHON_CMD" ]; then
    echo "Error: python or python3 command not found"
    exit 1
fi

# Check if pytest is available and install if needed
install_pytest_if_needed() {
    local python_cmd="$1"
    
    # Check if pytest is available as a Python module
    if $python_cmd -m pytest --version &>/dev/null; then
        return 0
    fi
    
    # pytest not found, attempt to install
    echo "pytest not found. Attempting to install in virtual environment..."
    
    # Determine pip command
    if [ -n "$VIRTUAL_ENV" ]; then
        # Virtual environment is active, use pip directly
        pip_cmd="pip"
        echo "Installing pytest using: $pip_cmd (virtual environment: $VIRTUAL_ENV)"
        $pip_cmd install --quiet pytest || {
            # Fallback: use python -m pip
            echo "pip command failed, trying: $python_cmd -m pip"
            $python_cmd -m pip install --quiet pytest || return 1
        }
    elif [ -f "$PROJECT_PATH/.venv/bin/pip" ]; then
        # Use virtual environment's pip directly
        pip_cmd="$PROJECT_PATH/.venv/bin/pip"
        echo "Installing pytest using: $pip_cmd (virtual environment: $PROJECT_PATH/.venv)"
        $pip_cmd install --quiet pytest || return 1
    elif [ -f "$PROJECT_PATH/venv/bin/pip" ]; then
        # Use virtual environment's pip directly
        pip_cmd="$PROJECT_PATH/venv/bin/pip"
        echo "Installing pytest using: $pip_cmd (virtual environment: $PROJECT_PATH/venv)"
        $pip_cmd install --quiet pytest || return 1
    else
        # Use python -m pip (should use the correct environment)
        echo "Installing pytest using: $python_cmd -m pip"
        $python_cmd -m pip install --quiet pytest || return 1
    fi
    
    # Verify installation
    if $python_cmd -m pytest --version &>/dev/null; then
        echo "pytest installed successfully"
        return 0
    else
        echo "Warning: pytest installation completed but still not available as module"
        return 1
    fi
}

# Install pytest if needed
if ! $PYTHON_CMD -m pytest --version &>/dev/null; then
    install_pytest_if_needed "$PYTHON_CMD"
fi

# Try to use python -m pytest first (ensures we use virtual environment's packages)
# If pytest is not installed as a module, fall back to pytest command
if $PYTHON_CMD -m pytest --version &>/dev/null; then
    echo "Running pytest collect-only using: $PYTHON_CMD -m pytest"
    $PYTHON_CMD -m pytest --collect-only -q --disable-warnings 2>&1
elif command -v pytest &>/dev/null; then
    echo "Warning: pytest not found as Python module, using system pytest command"
    echo "Running pytest collect-only using: pytest"
    pytest --collect-only -q --disable-warnings 2>&1
else
    echo "Error: pytest is not installed and installation failed. Please install pytest manually in the virtual environment using 'pip install pytest'"
    exit 1
fi
