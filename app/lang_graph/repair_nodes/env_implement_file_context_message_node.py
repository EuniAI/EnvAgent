import logging
import threading

from app.models.context import Context
from app.lang_graph.states.env_implement_state import EnvImplementState
from app.utils.logger_manager import get_thread_logger

class EnvRepairContextMessageNode:
    ENV_REPAIR_CONTEXT_QUERY = """\
REQUIREMENTS:
- Infer the current environment state from available setup scripts/outputs and test commands/outputs.
- Identify the root causes of the failing tests.
- Propose the minimal, actionable fixes to make tests pass: exact file edits, commands, env vars, and system dependencies with necessary version pins.
- If containers or external services are involved, include updated snippets and start/health-check steps.
- Provide validation: quick pre-checks, the exact test command to run, and expected success criteria.
- Return referenced key files and logs (prefer exact paths and line numbers).
- Prefer conservative, reproducible, deterministic changes; avoid unnecessary upgrades; be explicit and unambiguous.
"""

    def __init__(self, debug_mode: bool):
        self.debug_mode = debug_mode
        self._logger, _file_handler  = get_thread_logger(__name__)

    def __call__(self, state: EnvImplementState):
        env_implement_file_context_query = self.ENV_REPAIR_CONTEXT_QUERY
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
