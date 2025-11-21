from pathlib import Path

from app.lang_graph.states.env_implement_state import EnvImplementState, save_env_implement_states_to_json
from app.utils.lang_graph_util import get_last_message_content
from app.utils.logger_manager import get_thread_logger


class EnvImplementFileNode:
    """直接实现文件创建功能，不使用 agent，避免不稳定因素。"""

    def __init__(self, model, kg, local_path: str):
        """初始化节点。
        
        Args:
            model: 保留参数以兼容现有接口，但不再使用
            kg: 保留参数以兼容现有接口，但不再使用
            local_path: 项目根目录路径
        """
        self.local_path = local_path
        self._logger, _file_handler = get_thread_logger(__name__)
        # 保留空的 tools 列表以兼容 subgraph 中的 ToolNode
        self.tools = []

    def _determine_file_path(self, root_path: str) -> str:
        """确定要创建的文件路径。
        
        根据规则：
        1. 优先使用 "prometheus_setup.sh"
        2. 如果文件已存在且以 "prometheus" 开头，则覆盖
        3. 如果文件已存在但名称不以 "prometheus" 开头，则创建新文件（添加 "_2"）
        
        Args:
            root_path: 项目根目录路径
            
        Returns:
            相对路径字符串
        """
        base_filename = "prometheus_setup.sh"
        file_path = Path(root_path) / base_filename
        
        # 如果文件不存在，直接返回
        if not file_path.exists():
            return base_filename
        
        # 如果文件存在且以 "prometheus" 开头，覆盖
        if file_path.name.startswith("prometheus"):
            self._logger.info(f"File {base_filename} exists and starts with 'prometheus', will overwrite")
            return base_filename
        
        # 如果文件存在但不以 "prometheus" 开头，创建新文件
        name_without_ext = file_path.stem
        extension = file_path.suffix
        new_filename = f"{name_without_ext}_2{extension}"
        self._logger.info(f"File {base_filename} exists but doesn't start with 'prometheus', will create {new_filename}")
        return new_filename

    def __call__(self, state: EnvImplementState):
        """执行文件创建操作。
        
        Args:
            state: EnvImplementState 状态对象
            
        Returns:
            包含 env_implement_bash_path 的字典
        """
        # 从状态中获取 bash 脚本内容
        bash_content = get_last_message_content(state["env_implement_write_messages"])
        
        if not bash_content:
            self._logger.error("No bash content found in env_implement_write_messages")
            result = {}
            state.update(result)
            save_env_implement_states_to_json(state, self.local_path)
            return result
        
        # 确定文件路径
        relative_path = self._determine_file_path(self.local_path)
        file_path = Path(self.local_path) / relative_path
        
        # 如果文件存在且需要覆盖，先删除
        if file_path.exists():
            if file_path.name.startswith("prometheus"):
                file_path.unlink()
                self._logger.info(f"Deleted existing file: {relative_path}")
        
        # 创建文件（如果父目录不存在会自动创建）
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(bash_content)
        self._logger.info(f"Created bash script file: {relative_path}")
        
        # 准备返回结果
        result = {
            "env_implement_bash_path": relative_path
        }
        
        state.update(result)
        save_env_implement_states_to_json(state, self.local_path)
        return result
