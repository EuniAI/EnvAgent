# Python pytest Dockerfile
# 
# This Dockerfile automatically configures Python and pytest environment.
# 
# Usage:
#   docker build -t python-pytest .
#   docker run -it python-pytest /bin/bash
#
# Inside the container, you can install different Python versions using pyenv:
#   pyenv install 3.10
#   pyenv install 3.11
#   pyenv global 3.10  # or pyenv local 3.10 for current directory
#   python --version
#
# Features:
#   - Automatically installs Python and pytest environment
#   - pyenv is pre-installed for managing multiple Python versions at runtime
#   - Includes pytest plugins: pytest-cov, pytest-xdist, pytest-mock, pytest-timeout
#   - Includes Docker CLI for containerized testing scenarios

FROM ubuntu:24.04

# Avoid timezone prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Install essential build and system tools
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    wget \
    ca-certificates \
    gnupg \
    lsb-release \
    pkg-config \
    make \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncurses5-dev \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libffi-dev \
    liblzma-dev \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install pyenv for Python version management (available at runtime)
ENV PYENV_ROOT=/opt/pyenv
ENV PATH="${PYENV_ROOT}/bin:${PATH}"

RUN git clone https://github.com/pyenv/pyenv.git ${PYENV_ROOT} && \
    cd ${PYENV_ROOT} && \
    src/configure && \
    make -C src

# Install pyenv-virtualenv plugin for better venv management
RUN git clone https://github.com/pyenv/pyenv-virtualenv.git ${PYENV_ROOT}/plugins/pyenv-virtualenv

# Configure pyenv to be available in shell sessions
RUN echo 'export PYENV_ROOT="/opt/pyenv"' >> /etc/profile.d/pyenv.sh && \
    echo 'export PATH="${PYENV_ROOT}/bin:${PATH}"' >> /etc/profile.d/pyenv.sh && \
    echo 'eval "$(pyenv init -)"' >> /etc/profile.d/pyenv.sh && \
    echo 'eval "$(pyenv virtualenv-init -)"' >> /etc/profile.d/pyenv.sh

# Set working directory
WORKDIR /app

# Set environment variable to bypass PEP 668 system package restrictions
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Create symlink for python command (if not exists)
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Install pytest plus common plugins directly to system Python
# Note: pip, setuptools, and wheel are already installed via apt, so we skip upgrading them
# to avoid conflicts with system packages
RUN python3 -m pip install --no-cache-dir --break-system-packages \
    pytest \
    pytest-cov \
    pytest-xdist \
    pytest-mock \
    pytest-timeout

# Install Docker CLI (optional, for containerized testing scenarios)
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update && apt-get install -y docker-ce-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Verify installations
RUN echo "=== Environment Verification ===" && \
    python --version && \
    which python && \
    pip --version && \
    pytest --version && \
    pyenv --version && \
    echo "=== Verification Complete ===" && \
    echo "Note: You can install different Python versions at runtime using:" && \
    echo "  pyenv install <version>  # e.g., pyenv install 3.10" && \
    echo "  pyenv global <version>   # or pyenv local <version>"

# Copy project files
# COPY . /app/
