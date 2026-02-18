FROM ubuntu:24.04

# Avoid timezone prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Set working directory
WORKDIR /app

# Install essential build and development tools
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    curl \
    wget \
    jq \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    nodejs \
    npm \
    default-jdk \
    gcc \
    g++ \
    gdb \
    postgresql-client \
    mysql-client \
    sqlite3 \
    iputils-ping \
    vim \
    nano \
    zip \
    unzip \
    ca-certificates \
    gnupg \
    lsb-release

RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

RUN apt-get update && apt-get install -y docker-ce-cli

RUN apt-get clean
RUN rm -rf /var/lib/apt/lists/*
RUN ln -s /usr/bin/python3 /usr/bin/python

# Install pyright via npm (primary and recommended method)
# Pyright is primarily a Node.js tool distributed via npm, so npm installation is more reliable
RUN npm install -g pyright

# Verify pyright installation
RUN pyright --version || echo "Warning: pyright command not found in PATH"

# Copy project files
# COPY . /app/

# ARG HOST_UID
# ARG HOST_GID
# ARG HOST_USER

# RUN groupadd -g ${HOST_GID} ${HOST_USER} && \
#     useradd -m -u ${HOST_UID} -g ${HOST_GID} ${HOST_USER}

# USER ${HOST_USER}
