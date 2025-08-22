import uuid
from pathlib import Path
from typing import Optional, Sequence

from app.container.base_container import BaseContainer


class UserDefinedContainer(BaseContainer):
    def __init__(
        self,
        project_path: Path,
        workdir: Optional[str] = None,
        build_commands: Optional[Sequence[str]] = None,
        test_commands: Optional[Sequence[str]] = None,
        dockerfile_content: Optional[str] = None,
        image_name: Optional[str] = None,
    ):
        super().__init__(project_path, workdir)

        assert bool(dockerfile_content) != bool(image_name), (
            "Exactly one of dockerfile_content or image_name must be provided"
        )

        self.tag_name = f"prometheus_user_defined_container_{uuid.uuid4().hex[:10]}"
        self.build_commands = build_commands
        self.test_commands = test_commands
        self.dockerfile_content = dockerfile_content
        self.image_name = image_name

    def get_dockerfile_content(self) -> str:
        return self.dockerfile_content

    def build_docker_image(self):
        if self.dockerfile_content:
            super().build_docker_image()
        else:
            self._logger.info(f"Pulling docker image: {self.image_name}")
            pulled_image = self.client.images.pull(self.image_name)
            self._logger.info(f"Tagging pulled image as: {self.tag_name}")
            pulled_image.tag(repository=self.tag_name)

    def run_build(self) -> str:
        if self.build_commands is None:
            raise ValueError("build_commands is None. The user did not provide build commands.")

        command_output = ""
        for build_command in self.build_commands:
            command_output += f"$ {build_command}\n"
            command_output += f"{self.execute_command(build_command)}\n"
        return command_output

    def run_test(self) -> str:
        if self.test_commands is None:
            raise ValueError("test_commands is None. The user did not provide build commands.")

        command_output = ""
        for test_command in self.test_commands:
            command_output += f"$ {test_command}\n"
            command_output += f"{self.execute_command(test_command)}\n"
        return command_output
