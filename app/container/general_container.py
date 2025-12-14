import uuid
from pathlib import Path
from typing import Optional

from app.container.base_container import BaseContainer


class GeneralContainer(BaseContainer):
    """A general-purpose container with a comprehensive development environment.

    This container provides a full Ubuntu-based development environment with common
    development tools and languages pre-installed, including Python, Node.js, Java,
    and various build tools. It's designed to be a flexible container that can
    handle various types of projects through direct command execution rather than
    predefined build and test methods.

    The container includes:
        - Build tools (gcc, g++, cmake, make)
        - Programming languages (Python 3, Node.js, Java)
        - Development tools (git, gdb)
        - Database clients (PostgreSQL, MySQL, SQLite)
        - Text editors (vim, nano)
        - Docker CLI for container management
        - Various utility tools (curl, wget, zip, etc.)

    Unlike specialized containers, this container does not implement run_build() or
    run_test() methods. Instead, the agent will use execute_command() directly for
    custom build and test operations.
    """

    def __init__(self, project_path: Path, project_dir: Path, dockerfile_template_path: Optional[Path] = None):
        """Initialize the general container with a unique tag name.

        Args:
            project_path (Path): Path to the project directory to be containerized.
            dockerfile_template_path (Optional[Path]): Optional path to a Dockerfile template file.
                If provided, the Dockerfile content will be read from this file instead of using
                the default hardcoded content. If None, uses the default Dockerfile content.
        """
        super().__init__(project_path, project_dir)
        self.tag_name = f"prometheus_envagent_container_{uuid.uuid4().hex[:10]}"
        self.dockerfile_template_path = dockerfile_template_path

    def get_dockerfile_content(self) -> str:
        """Get the Dockerfile content for the general-purpose container.

        If a dockerfile_template_path was provided during initialization, reads the
        Dockerfile content from that file. Otherwise, returns the default hardcoded
        Dockerfile content.

        The Dockerfile sets up an Ubuntu-based environment with a comprehensive
        set of development tools and languages installed. It includes Python,
        Node.js, Java, and various build tools, making it suitable for different
        types of projects.

        Returns:
            str: Content of the Dockerfile as a string.

        Raises:
            FileNotFoundError: If dockerfile_template_path was provided but the file doesn't exist.
            IOError: If there's an error reading the Dockerfile template file.
        """
        # If a template path was provided, read from file
        if self.dockerfile_template_path:
            template_path = Path(self.dockerfile_template_path)
            if not template_path.exists():
                raise FileNotFoundError(
                    f"Dockerfile template not found: {self.dockerfile_template_path}"
                )
            self._logger.info(f"Reading Dockerfile from template: {self.dockerfile_template_path}")
            return template_path.read_text(encoding="utf-8")
        else:
            raise Exception("No Dockerfile template path provided")


    def run_build(self):
        """Not implemented for GeneralContainer.

        This method is intentionally not implemented as the GeneralContainer is designed
        to use execute_command() directly for custom build operations.

        Raises:
            NotImplementedError: Always raises this exception to indicate that direct
                command execution should be used instead.
        """
        raise NotImplementedError(
            "GeneralContainer does not support run_build, use execute_command directly"
        )

    def run_test(self):
        """Not implemented for GeneralContainer.

        This method is intentionally not implemented as the GeneralContainer is designed
        to use execute_command() directly for custom test operations.

        Raises:
            NotImplementedError: Always raises this exception to indicate that direct
                command execution should be used instead.
        """
        raise NotImplementedError(
            "GeneralContainer does not support run_test, use execute_command directly"
        )
