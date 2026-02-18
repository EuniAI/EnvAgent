FROM ubuntu:24.04

# Avoid timezone prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Set working directory
WORKDIR /app

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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Switch system shell from dash to bash (critical step)
# This solves most script compatibility issues
RUN apt-get update -y && apt-get install -y --no-install-recommends debconf-utils \
    && echo 'dash dash/sh boolean false' | debconf-set-selections \
    && dpkg-reconfigure -f noninteractive dash \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update && apt-get install -y docker-ce-cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Verify basic installations
RUN gcc --version && \
    make --version && \
    git --version && \
    curl --version
