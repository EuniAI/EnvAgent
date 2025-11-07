
from app.lang_graph.states.bug_reproduction_state import BugReproductionState
from app.utils.logger_manager import get_thread_logger


class BugReproductionContextMessageNode:
    BUG_REPRODUCING_QUERY = """\
OBJECTIVE: Find existing test commands in the codebase to verify the project runs correctly.

Search for:
- Test runner commands (pytest, npm test, go test, cargo test, etc.)
- Build and test scripts in Makefile, package.json, setup.py, Cargo.toml
- CI/CD test commands in .github/workflows, .gitlab-ci.yml
- Docker test services
- Test configuration files

Requirements:
- Return actual test commands found in the codebase
- Include command syntax and file locations
- Cover multiple programming languages if present
- Focus on commands that verify basic functionality

Examples of what to look for:
- Python: pytest, python -m pytest, tox
- Node.js: npm test, yarn test, jest
- Go: go test, go test ./...
- Rust: cargo test, cargo check
- Java: mvn test, gradle test
- Makefile: make test, make check

Find the test commands that can verify this codebase works correctly.
"""

    def __init__(self):
        self._logger, _file_handler = get_thread_logger(__name__)

    def __call__(self, state: BugReproductionState):
        bug_reproducing_query = self.BUG_REPRODUCING_QUERY
        self._logger.debug(f"Sending query to context provider subgraph:\n{bug_reproducing_query}")
        return {"bug_reproducing_query": bug_reproducing_query}
