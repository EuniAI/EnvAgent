import logging
import threading

from app.models.context import Context
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
        self._logger, _file_handler  = get_thread_logger(__name__)

    def __call__(self, state: EnvImplementState):
        env_implement_file_context_query = self.ENV_IMPLEMENT_FILE_CONTEXT_QUERY
        self._logger.debug(f"Sending environment configuration query to context provider subgraph:\n{env_implement_file_context_query}")
        
        # 返回状态更新，只包含需要更新的字段
        if self.debug_mode:
          return {
              "env_implement_file_context_query": env_implement_file_context_query,
              "env_implement_file_context": [
                  Context(relative_path='flink-end-to-end-tests/test-scripts/docker-hadoop-secure-cluster/docker-compose.yml', content='18. version: \'3.5\'\n19. \n20. networks:\n21.   docker-hadoop-cluster-network:\n22.     name: docker-hadoop-cluster-network\n23. \n24. services:\n25.   kdc:\n26.     build: kdc\n27.     container_name: "kdc"\n28.     hostname: kdc.kerberos.com\n29.     image: flink/test-kdc:latest\n30.     networks:\n31.       - docker-hadoop-cluster-network\n32.     environment:\n33.       REALM: EXAMPLE.COM\n34.       DOMAIN_REALM: kdc.kerberos.com\n35. \n36.   master:\n37.     build: hadoop\n38.     image: ${DOCKER_HADOOP_IMAGE_NAME:-flink/test-hadoop:latest}\n39.     command: master\n40.     depends_on:\n41.       - kdc\n42.     container_name: "master"\n43.     hostname: master.docker-hadoop-cluster-network\n44.     networks:\n45.       - docker-hadoop-cluster-network\n46.     environment:\n47.       KRB_REALM: EXAMPLE.COM\n48.       DOMAIN_REALM: kdc.kerberos.com\n49. \n50.   worker1:\n51.     build: hadoop\n52.     image: ${DOCKER_HADOOP_IMAGE_NAME:-flink/test-hadoop:latest}\n53.     command: worker\n54.     depends_on:\n55.       - kdc\n56.       - master\n57.     container_name: "worker1"\n58.     hostname: worker1.docker-hadoop-cluster-network\n59.     networks:\n60.       - docker-hadoop-cluster-network\n61.     environment:\n62.       KRB_REALM: EXAMPLE.COM\n63.       DOMAIN_REALM: kdc.kerberos.com\n64. \n65.   worker2:\n66.     build: hadoop\n67.     image: ${DOCKER_HADOOP_IMAGE_NAME:-flink/test-hadoop:latest}\n68.     command: worker\n69.     depends_on:\n70.       - kdc\n71.       - master\n72.     container_name: "worker2"\n73.     hostname: worker2.docker-hadoop-cluster-network\n74.     networks:\n75.       - docker-hadoop-cluster-network\n76.     environment:\n77.       KRB_REALM: EXAMPLE.COM\n78.       DOMAIN_REALM: kdc.kerberos.com', start_line_number=18, end_line_number=78), 
                  Context(relative_path='flink-python/setup.py', content='31. if sys.version_info < (3, 9):\n32.     print("Python versions prior to 3.9 are not supported for PyFlink.",\n33.           file=sys.stderr)\n34.     sys.exit(-1)', start_line_number=31, end_line_number=34), 
                  Context(relative_path='flink-python/setup.py', content='319.     install_requires = [\'py4j==0.10.9.7\', \'python-dateutil>=2.8.0,<3\',\n320.                         \'apache-beam>=2.54.0,<=2.61.0\',\n321.                         \'cloudpickle>=2.2.0\', \'avro>=1.12.0\',\n322.                         \'pytz>=2018.3\', \'fastavro>=1.1.0,!=1.8.0\', \'requests>=2.26.0\',\n323.                         \'protobuf>=3.19.0\',\n324.                         \'numpy>=1.22.4\',\n325.                         \'pandas>=1.3.0\',\n326.                         \'pyarrow>=5.0.0,<21.0.0\',\n327.                         \'pemja>=0.5.0,<0.5.4;platform_system != "Windows"\',\n328.                         \'httplib2>=0.19.0\',\n329.                         \'ruamel.yaml>=0.18.4\',\n330.                         apache_flink_libraries_dependency]', start_line_number=319, end_line_number=330), 
                  Context(relative_path='flink-dist/src/main/resources/config.yaml', content='19. # These parameters are required for Java 17 support.\n20. # They can be safely removed when using Java 8/11.\n21. env:\n22.   java:\n23.     opts:\n24.       all: --add-exports=java.rmi/sun.rmi.registry=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.file=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.parser=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.tree=ALL-UNNAMED --add-exports=jdk.compiler/com.sun.tools.javac.util=ALL-UNNAMED --add-exports=java.security.jgss/sun.security.krb5=ALL-UNNAMED --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.net=ALL-UNNAMED --add-opens=java.base/java.io=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED --add-opens=java.base/sun.nio.ch=ALL-UNNAMED --add-opens=java.base/java.lang.reflect=ALL-UNNAMED --add-opens=java.base/java.text=ALL-UNNAMED --add-opens=java.base/java.time=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED --add-opens=java.base/java.util.concurrent=ALL-UNNAMED --add-opens=java.base/java.util.concurrent.atomic=ALL-UNNAMED --add-opens=java.base/java.util.concurrent.locks=ALL-UNNAMED', start_line_number=19, end_line_number=24), 
                  Context(relative_path='README.md', content='1. # Apache Flink\n2. \n3. Apache Flink is an open source stream processing framework with powerful stream- and batch-processing capabilities.\n4. \n5. Learn more about Flink at [https://flink.apache.org/](https://flink.apache.org/)\n6. \n7. \n8. ### Features\n9. \n10. * A streaming-first runtime that supports both batch processing and data streaming programs', start_line_number=1, end_line_number=10)
              ]
          }
        else:
          return {
              "env_implement_file_context_query": env_implement_file_context_query,
          }
