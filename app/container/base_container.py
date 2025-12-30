import logging
import os
import shutil
import tarfile
import tempfile
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Sequence

import docker  # Docker SDK for Python
from docker.errors import ImageNotFound

from app.utils.logger_manager import get_thread_logger


class CommandResult:
    def __init__(self, stdout, stderr, returncode):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class BaseContainer(ABC):
    """An abstract base class for managing Docker containers with file synchronization capabilities.

    This class provides core functionality for creating, managing, and interacting with Docker
    containers. It handles container lifecycle operations including building images, starting
    containers, updating files, and cleanup. The class is designed to be extended for specific
    container implementations that specifies the Dockerfile, how to build and how to run the test.
    """

    client: docker.DockerClient
    tag_name: str
    workdir: str = "/app"
    container: docker.models.containers.Container
    project_path: Path
    timeout: int = 120
    logger: logging.Logger

    def __init__(self, project_path: Path, project_dir: Path, workdir: Optional[str] = None, temp_prefix: str = "tmp_envagent"):
        """Initialize the container with a project directory.

        Creates a temporary copy of the project directory to work with.

        Args:
          project_path: Path to the project directory to be containerized.
          project_dir: Path to the project directory to save the results.
          workdir: Optional working directory inside the container.
          temp_prefix: Prefix for the temporary directory name. Defaults to "env".
        """
        # Initialize Docker client
        self.client = docker.from_env(timeout=240)

        self._logger, _file_handler = get_thread_logger(__name__)

        # Create temp directory with project_path.name as suffix
        unique_suffix = uuid.uuid4().hex[:8]
        temp_dir_name = f"{temp_prefix}_{unique_suffix}_{project_path.name}"
        temp_dir = Path(project_dir / temp_dir_name)
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_project_path = temp_dir / project_path.name
        shutil.copytree(project_path, temp_project_path)
        self.project_path = temp_project_path.absolute()
        self._logger.info(f"Created temporary project directory: {self.project_path}")

        if workdir:
            self.workdir = workdir
        self._logger.debug(f"Using workdir: {self.workdir}")

        self.container = None

    @abstractmethod
    def get_dockerfile_content(self) -> str:
        """Get the content of the Dockerfile for building the container image.

        Returns:
            str: Content of the Dockerfile as a string.
        """
        pass

    def build_docker_image(self):
        """Build a Docker image using the Dockerfile content.

        Creates a Dockerfile in the project directory and builds a Docker image
        using the specified tag name.
        """
        
        host_user = os.getenv("USER") or os.getenv("USERNAME") or "lix"
        host_uid = os.getuid()
        host_gid = os.getgid()

        dockerfile_content = self.get_dockerfile_content()

        if "USE EXISTING IMAGE" in dockerfile_content:
            self._logger.info(f"Using existing image {self.tag_name}")
            try:
                self.client.images.get(self.tag_name)
                self._logger.info(f"Image {self.tag_name} found locally")
                return True
            except ImageNotFound:
                # If image not local, attempt to pull; otherwise surface the error
                self._logger.info(f"Image {self.tag_name} not found locally")
                return False

        dockerfile_path = self.project_path / "Dockerfile"
        dockerfile_path.write_text(dockerfile_content)
        self._logger.info(f"Building docker image {self.tag_name}")
        self.client.images.build(
            path=str(self.project_path), 
            dockerfile=dockerfile_path.name, 
            tag=self.tag_name,
            # buildargs={
            #     "HOST_USER": host_user,
            #     "HOST_UID": str(host_uid),
            #     "HOST_GID": str(host_gid),
            # },
            # rm=True,
        )

    def build_empty_docker_image(self):
        """Build a empty Docker image.

        Builds a Docker image using the specified tag name.
        Creates a minimal Dockerfile if one doesn't exist.
        """
        self._logger.info(f"Building empty docker image {self.tag_name}")
        
        # Create a minimal Dockerfile if it doesn't exist
        dockerfile_path = self.project_path / "Dockerfile"
        if not dockerfile_path.exists():
            # Use the same base image as GeneralContainer for consistency
            minimal_dockerfile = """FROM ubuntu:24.04

# Avoid timezone prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# Set working directory
WORKDIR /app
"""
            dockerfile_path.write_text(minimal_dockerfile)
            self._logger.info(f"Created minimal Dockerfile at {dockerfile_path}")
        
        self.client.images.build(path=str(self.project_path), tag=self.tag_name)

    def start_container(self, use_volume_mapping: bool = False):
        """Start a Docker container from the built image.

        Starts a detached container with TTY enabled and mounts the Docker socket.
        Optionally uses volume mapping for real-time file synchronization.

        Args:
            use_volume_mapping (bool): If True, maps project directory as volume for
                                     real-time bidirectional file sync. Defaults to False.
        """
        self._logger.info(f"Starting container from image {self.tag_name}")

        # Base volumes (Docker socket)
        volumes = {"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"}}

        # Add volume mapping if requested
        if use_volume_mapping:
            volumes[str(self.project_path)] = {"bind": self.workdir, "mode": "rw"}
            self._logger.info(f"Using volume mapping: {self.project_path} -> {self.workdir}")

        # Get current user UID and GID to pass to container
        # The entrypoint script will create the user and switch to it
        environment = {"PYTHONPATH": f"{self.workdir}:$PYTHONPATH"}
        if os.name != 'nt':  # Unix-like systems only
            try:
                host_uid = os.getuid()
                host_gid = os.getgid()
                host_user = os.getenv('USER', os.getenv('USERNAME', 'appuser'))
                # Pass user info as environment variables for entrypoint script
                environment["HOST_UID"] = str(host_uid)
                environment["HOST_GID"] = str(host_gid)
                environment["HOST_USER"] = host_user
                self._logger.info(f"Container will run as user {host_user} (UID:{host_uid}, GID:{host_gid})")
            except (AttributeError, OSError) as e:
                self._logger.warning(f"Could not get user ID, container will run as root: {e}")

        container_kwargs = {
            "detach": True,
            "tty": True,
            "network_mode": "host",
            "environment": environment,
            "volumes": volumes,
        }

        self.container = self.client.containers.run(
            self.tag_name,
            **container_kwargs
        )
        # Print container information after starting
        self.print_container_info()

    def _fix_file_permissions_after_command(self):
        """Fix file ownership after command execution.
        
        Changes ownership of all files in workdir to host user, allowing the host
        user to modify files created by root in the container.
        """
        if not self.container:
            return
            
        if os.name != 'nt':  # Unix-like systems only
            try:
                host_uid = os.getuid()
                host_gid = os.getgid()
                
                # Change ownership of workdir to host user (递归修改所有文件)
                chown_command = f"chown -R {host_uid}:{host_gid} {self.workdir} 2>/dev/null || true"
                self._logger.debug(f"Fixing file permissions: chown {host_uid}:{host_gid}")
                
                # Execute as root (container default user)
                exec_result = self.container.exec_run(
                    f'/bin/bash -c "{chown_command}"',
                    workdir=self.workdir
                )
                
                if exec_result.exit_code == 0:
                    self._logger.debug(f"File permissions fixed successfully")
                else:
                    # 不要警告，因为有些文件可能本来就不需要修改
                    self._logger.debug(f"Some files may not have changed ownership (this is normal)")
                    
            except (AttributeError, OSError) as e:
                self._logger.debug(f"Could not fix file permissions: {e}")

    def is_running(self) -> bool:
        return bool(self.container)

    def get_container_id(self) -> str:
        """Get the container ID.

        Returns:
            str: The full container ID.
        """
        if not self.container:
            raise RuntimeError("Container is not running")
        return self.container.id

    def get_container_short_id(self) -> str:
        """Get the container short ID.

        Returns:
            str: The short container ID (first 12 characters).
        """
        if not self.container:
            raise RuntimeError("Container is not running")
        return self.container.short_id

    def get_container_name(self) -> str:
        """Get the container name.

        Returns:
            str: The container name.
        """
        if not self.container:
            raise RuntimeError("Container is not running")
        return self.container.name

    def get_docker_exec_command(self) -> str:
        """Get the docker exec command to enter the container.

        Returns:
            str: The docker exec command string.
        """
        if not self.container:
            raise RuntimeError("Container is not running")
        container_id = self.get_container_short_id()
        return f"docker exec -it {container_id} /bin/bash"

    def print_container_info(self):
        """Print container information including ID and exec command."""
        if not self.container:
            self._logger.warning("Container is not running")
            return

        container_id = self.get_container_id()
        short_id = self.get_container_short_id()
        container_name = self.get_container_name()
        exec_command = self.get_docker_exec_command()
        mapping_project_path = self.project_path

        self._logger.info(f"Container ID: {container_id}")
        self._logger.info(f"Container Short ID: {short_id}")
        self._logger.info(f"Container Name: {container_name}")
        self._logger.info(f"To enter container, run: {exec_command}")
        self._logger.info(f"Project path: {mapping_project_path}")

    def get_generated_files(self, file_pattern: str = "*") -> list[Path]:
        """Get files generated in the container that are now available on the host.

        This method works when volume mapping is enabled, allowing real-time access
        to files created inside the container.

        Args:
            file_pattern (str): Pattern to match files (e.g., "Dockerfile*", "*.log")

        Returns:
            list[Path]: List of generated files found on the host
        """
        if not self.container:
            self._logger.warning("Container is not running")
            return []

        generated_files = []
        try:
            # List files in the container's workdir
            result = self.execute_command(f"find {self.workdir} -name '{file_pattern}' -type f")
            if result.strip():
                for line in result.strip().split("\n"):
                    if line.strip():
                        # Convert container path to host path
                        container_path = line.strip()
                        if container_path.startswith(self.workdir):
                            relative_path = container_path[len(self.workdir) :].lstrip("/")
                            host_path = self.project_path / relative_path
                            if host_path.exists():
                                generated_files.append(host_path)
                                self._logger.info(f"Found generated file: {host_path}")
        except Exception as e:
            self._logger.error(f"Error listing generated files: {e}")

        return generated_files

    def get_dockerfile_from_container(self) -> Optional[Path]:
        """Get the Dockerfile generated in the container.

        Returns:
            Optional[Path]: Path to the Dockerfile on the host, or None if not found
        """
        dockerfiles = self.get_generated_files("Dockerfile*")
        if dockerfiles:
            # Return the first Dockerfile found
            return dockerfiles[0]
        return None

    def update_files(
        self, project_root_path: Path, updated_files: Sequence[Path], removed_files: Sequence[Path]
    ):
        """Update files in the running container with files from a local directory.

        Creates a tar archive of the new files and copies them into the workdir of the container.

        Args:
          new_project_path: Path to the directory containing new files.
        """
        if not project_root_path.is_absolute():
            raise ValueError("project_root_path {project_root_path} must be a absolute path")

        self._logger.info("Updating files in the container after edits.")
        for file in removed_files:
            self._logger.info(f"Removing file {file} in the container")
            self.execute_command(f"rm {file}")

        parent_dirs = {str(file.parent) for file in updated_files}
        for dir_path in sorted(parent_dirs):
            self._logger.info(f"Creating directory {dir_path} in the container")
            self.execute_command(f"mkdir -p {dir_path}")

        with tempfile.NamedTemporaryFile() as temp_tar:
            with tarfile.open(fileobj=temp_tar, mode="w") as tar:
                for file in updated_files:
                    local_absolute_file = project_root_path / file
                    self._logger.info(f"Updating {file} in the container")
                    tar.add(local_absolute_file, arcname=str(file))

            temp_tar.seek(0)

            self.container.put_archive(self.workdir, temp_tar.read())

        self._logger.info("Files updated successfully")

    @abstractmethod
    def run_build(self):
        """Run build commands in the container.

        This method should be implemented by subclasses to define build steps.
        """
        pass

    @abstractmethod
    def run_test(self):
        """Run test commands in the container.

        This method should be implemented by subclasses to define test steps.
        """
        pass

    def execute_command(self, command: str) -> str:
        """Execute a command in the running container.

        Args:
            command: Command to execute in the container.

        Returns:
            str: Output of the command as a string.
        """
        timeout_msg = f"""
        *******************************************************************************
        {command} timeout after {self.timeout} seconds
        *******************************************************************************
        """
        timeout_command = f"timeout -k 5 {self.timeout}s {command}"
        command = f'/bin/bash -l -c "{timeout_command}"'
        self._logger.debug(f"Running command in container: {command}")
        exec_result = self.container.exec_run(command, workdir=self.workdir)
        exec_result_str = exec_result.output.decode("utf-8")

        if exec_result.exit_code in (124, 137):
            exec_result_str += timeout_msg

        self._logger.debug(f"Command output:\n{exec_result_str}")
        return exec_result_str

    def execute_command_with_exit_code(self, command: str, fix_permissions: bool = True, timeout: Optional[int] = None, print_output: bool = True):
        """Execute a command in the running container and return both output and exit code.

        Args:
            command: Command to execute in the container.
            fix_permissions: If True (default), automatically fix file ownership to host user
                           after command execution. This allows host user to modify files
                           created by root in the container.
            timeout: Optional timeout in seconds. If None, uses self.timeout (default 120s).
                    For long-running commands like npm install/build, set a longer timeout.

        Returns:
            object: An object with stdout, stderr, and returncode attributes.
        """
        # Use timeout if specified, otherwise use default timeout
        timeout_value = timeout if timeout is not None else self.timeout
        timeout_msg = f"""
        *******************************************************************************
        {command} timeout after {timeout_value} seconds
        *******************************************************************************
        """
        timeout_command = f"timeout -k 5 {timeout_value}s {command}"
        wrapped_command = f'/bin/bash -l -c "{timeout_command}"'
        self._logger.debug(f"Running command in container: {wrapped_command}")
        exec_result = self.container.exec_run(wrapped_command, workdir=self.workdir)
        exec_result_str = exec_result.output.decode("utf-8")

        if exec_result.exit_code in (124, 137):
            exec_result_str += timeout_msg

        if print_output:
            self._logger.debug(f"Command output:\n{exec_result_str}")
        
        # 执行完命令后，自动修复文件权限
        if fix_permissions:
            self._fix_file_permissions_after_command()

        return CommandResult(exec_result_str, "", exec_result.exit_code)

    def restart_container(self, use_volume_mapping: bool = False):
        """Restart the container with optional volume mapping.

        Args:
            use_volume_mapping (bool): If True, maps project directory as volume for
                                     real-time bidirectional file sync. Defaults to False.
        """
        self._logger.info("Restarting the container")
        if self.container:
            self.container.stop(timeout=10)
            self.container.remove(force=True)

        self.start_container(use_volume_mapping=use_volume_mapping)

    def save_container_as_image(self, image_name: str, tag: str = "latest") -> str:
        """Save the current running container as a Docker image with a fixed name.

        Creates a new Docker image from the current container state using docker commit.
        The image will be tagged with the specified name and tag.

        Args:
            image_name (str): The name for the saved image (e.g., "my-project-image").
            tag (str): The tag for the image. Defaults to "latest".

        Returns:
            str: The full image name with tag (e.g., "my-project-image:latest").

        Raises:
            RuntimeError: If the container is not running.
        """
        if not self.container:
            raise RuntimeError("Container is not running. Cannot save container as image.")

        full_image_name = f"{image_name}:{tag}"
        self._logger.info(f"Saving container {self.get_container_short_id()} as image {full_image_name}")

        try:
            # Commit the container to create a new image
            image = self.container.commit(repository=image_name, tag=tag)
            self._logger.info(f"Successfully saved container as image: {full_image_name}")
            self._logger.info(f"Image ID: {image.id}")
            return full_image_name
        except Exception as e:
            self._logger.error(f"Failed to save container as image: {e}")
            raise

    def cleanup(self):
        """Clean up container resources and temporary files.

        Stops and removes the container, removes the Docker image,
        and deletes temporary project files.
        """
        self._logger.info("Cleaning up container and temporary files")
        if self.container:
            self.container.stop(timeout=10)
            self.container.remove(force=True)
            self.container = None
            self.client.images.remove(self.tag_name, force=True)

        shutil.rmtree(self.project_path)
