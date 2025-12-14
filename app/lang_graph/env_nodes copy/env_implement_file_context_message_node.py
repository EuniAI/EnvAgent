
from app.lang_graph.states.env_implement_state import EnvImplementState
from app.utils.logger_manager import get_thread_logger


class EnvImplementFileContextMessageNode:
    ENV_IMPLEMENT_FILE_CONTEXT_QUERY = """\
OBJECTIVE: Find the most relevant environment configuration files that can help generate an accurate Dockerfile for this project,
including Dockerfiles, dependency files, build configurations, and environment setup files.

<reasoning>
1. Analyze project characteristics:
   - Programming language and framework
   - Dependency management files
   - Build system and tools
   - Runtime requirements
   - Environment configurations

2. Search requirements:
   - Existing Dockerfiles or containerization files
   - Dependency files (requirements.txt, package.json, pom.xml, etc.)
   - Build configuration files (Makefile, CMakeLists.txt, etc.)
   - Environment configuration files (.env, config files)
   - Setup and installation scripts

3. Focus areas:
   - Docker-related files (Dockerfile, docker-compose.yml, .dockerignore)
   - Package management files (requirements.txt, package.json, go.mod, Cargo.toml, etc.)
   - Build system files (Makefile, CMakeLists.txt, build.gradle, etc.)
   - Environment configuration (.env, config.json, application.properties, etc.)
   - Setup documentation (README.md, INSTALL.md, SETUP.md)
   - CI/CD configuration files
</reasoning>

REQUIREMENTS:
- Return the most relevant environment configuration files for Dockerfile generation
- Must include complete file content with exact file paths and line numbers
- Must include dependency files, build configurations, and environment setups
- Must include any existing Docker-related files
- Must include setup documentation and installation instructions

<examples>
<example id="python-web-app">
<project_context>
Python Flask web application with requirements.txt
</project_context>

<ideal_files>
# File: requirements.txt
Flask==2.3.3
gunicorn==21.2.0
psycopg2-binary==2.9.7
redis==4.6.0

# File: app.py
from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello():
    return 'Hello World!'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

# File: README.md
## Installation
pip install -r requirements.txt
python app.py
</ideal_files>
</example>

<example id="nodejs-api">
<project_context>
Node.js Express API with package.json
</project_context>

<ideal_files>
# File: package.json
{
  "name": "my-api",
  "version": "1.0.0",
  "scripts": {
    "start": "node server.js",
    "dev": "nodemon server.js"
  },
  "dependencies": {
    "express": "^4.18.2",
    "mongoose": "^7.5.0"
  }
}

# File: server.js
const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

app.get('/', (req, res) => {
  res.json({ message: 'API is running' });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
</ideal_files>
</example>

Search priority:
1. Existing Dockerfiles or containerization files
2. Dependency management files (requirements.txt, package.json, etc.)
3. Build configuration files (Makefile, CMakeLists.txt, etc.)
4. Environment configuration files (.env, config files)
5. Setup documentation and installation instructions

Find the most relevant environment configuration files with complete context for Dockerfile generation.
"""

    def __init__(self, debug_mode: bool):
        self.debug_mode = debug_mode
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: EnvImplementState):
        env_implement_file_context_query = self.ENV_IMPLEMENT_FILE_CONTEXT_QUERY
        self._logger.debug(
            f"Sending environment configuration query to context provider subgraph:\n{env_implement_file_context_query}"
        )

        return {
            "env_implement_file_context_query": env_implement_file_context_query,
        }
