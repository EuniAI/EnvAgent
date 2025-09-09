# Repository-Based Logic 说明

本文档说明了从 Prometheus 项目迁移过来的 repository-based 逻辑功能。

## 功能概述

Repository-based 逻辑的核心思想是：**避免重复处理相同的代码仓库**。

- 如果之前已经处理过相同的 `URL + commit_id` 组合，系统会直接复用已有的知识图谱
- 如果是新的组合，系统会克隆仓库、构建知识图谱并保存元数据

## 主要组件

### 1. Repository 模型 (`app/models/repository.py`)

定义了仓库的元数据结构：

```python
@dataclass
class Repository:
    url: str                    # 仓库URL
    commit_id: Optional[str]    # 提交ID (None表示最新提交)
    playground_path: str        # 本地克隆路径
    kg_root_node_id: int       # 知识图谱根节点ID
    kg_max_ast_depth: int      # AST最大深度
    kg_chunk_size: int         # 文本块大小
    kg_chunk_overlap: int      # 文本块重叠大小
```

### 2. RepositoryStorage 类

提供基于JSON文件的持久化存储：

- `get_repository_by_url_and_commit_id()`: 根据URL和commit_id查找仓库
- `save_repository()`: 保存仓库元数据
- `delete_repository()`: 删除仓库元数据

### 3. 增强的 RepositoryService

新增的核心方法：

```python
def get_or_create_repository(
    self, github_token: str, https_url: str, commit_id: Optional[str] = None
) -> tuple[Path, int, bool]:
    """获取现有仓库或创建新仓库
    
    Returns:
        Tuple of (repository_path, kg_root_node_id, is_new_repository)
    """
```

## 工作流程

1. **检查现有仓库**: 根据 `URL + commit_id` 查找已存在的仓库元数据
2. **路径验证**: 如果找到元数据，验证本地路径是否仍然存在
3. **复用或创建**: 
   - 如果路径存在 → 复用现有仓库和知识图谱
   - 如果路径不存在或没有元数据 → 创建新仓库
4. **保存元数据**: 新建仓库时保存元数据供后续复用

## 使用示例

### 在 main.py 中的使用

```python
# 旧的方式 (每次都重新克隆和构建)
repo_path = repository_service.clone_github_repo(github_token, github_url)
root_node_id = knowledge_graph_service.build_and_save_knowledge_graph(repo_path)

# 新的方式 (repository-based)
repo_path, root_node_id, is_new_repository = repository_service.get_or_create_repository(
    github_token, github_url, commit_id
)

if is_new_repository:
    print("创建了新仓库")
else:
    print("复用了现有仓库")
```

### 清理资源

```python
# 根据是否为新仓库决定清理策略
if is_new_repository:
    # 清理新创建的资源
    repository_service.clean_repository(github_url, commit_id)
else:
    # 保留共享资源供后续使用
    print("保留现有仓库资源")
```

## 存储格式

仓库元数据存储在 `{working_dir}/repository_metadata.json` 文件中：

```json
[
  {
    "url": "https://github.com/user/repo.git",
    "commit_id": "abc123def456...",
    "playground_path": "/path/to/working_dir/repositories/unique_id",
    "kg_root_node_id": 42,
    "kg_max_ast_depth": 3,
    "kg_chunk_size": 1000,
    "kg_chunk_overlap": 200
  }
]
```

## 优势

1. **性能提升**: 避免重复克隆和构建知识图谱
2. **资源节约**: 减少磁盘空间和Neo4j存储使用
3. **时间节约**: 大型仓库的处理时间显著减少
4. **一致性**: 相同仓库版本使用相同的知识图谱

## 注意事项

1. **存储空间**: 系统会保留已处理的仓库，需要定期清理
2. **版本控制**: 不同的 commit_id 会被视为不同的仓库
3. **路径变化**: 如果工作目录改变，需要重新构建仓库
4. **并发安全**: 当前实现不支持并发访问，需要外部同步

## 测试

运行测试脚本验证功能：

```bash
python test_repository_storage_only.py
```

测试涵盖：
- 仓库元数据的保存和检索
- 不同URL和commit_id组合的处理
- None commit_id的支持
- 仓库更新和删除功能

## 仓库管理

### 删除仓库

系统提供了多种删除仓库的方法：

#### 1. 编程方式删除

```python
# 删除特定的仓库（URL + commit_id组合）
success = repository_service.delete_repository(
    "https://github.com/user/repo.git", 
    "abc123def456..."
)

# 删除最新版本的仓库（commit_id为None）
success = repository_service.delete_repository(
    "https://github.com/user/repo.git", 
    None
)

# 查找某个URL的所有版本
all_versions = repository_service.find_repositories_by_url(
    "https://github.com/user/repo.git"
)

# 列出所有仓库
all_repos = repository_service.list_repositories()
```

#### 2. 命令行工具

使用 `manage_repositories.py` 脚本进行管理：

```bash
# 列出所有仓库
python manage_repositories.py list

# 查看特定仓库详情
python manage_repositories.py info "https://github.com/user/repo.git"
python manage_repositories.py info "https://github.com/user/repo.git" --commit-id abc123

# 删除特定仓库
python manage_repositories.py delete "https://github.com/user/repo.git" --commit-id abc123

# 强制删除（无需确认）
python manage_repositories.py delete "https://github.com/user/repo.git" --force

# 删除某个URL的所有版本
python manage_repositories.py delete-all-commits "https://github.com/user/repo.git"

# 导出仓库列表
python manage_repositories.py export --format table
python manage_repositories.py export --format json
```

### 删除操作说明

删除仓库时会执行以下操作：

1. **检查存在性**: 验证仓库元数据是否存在
2. **清理文件**: 删除本地克隆的仓库文件和目录
3. **清理知识图谱**: 从Neo4j数据库中删除相关的知识图谱节点
4. **清理元数据**: 从JSON存储中删除仓库元数据
5. **返回状态**: 返回操作成功或失败的状态

### 安全考虑

- 删除操作是**不可逆的**，请谨慎操作
- 建议在删除前使用 `info` 命令确认仓库信息
- 可以使用 `export` 命令备份仓库元数据
- 删除前会显示详细信息并要求确认（除非使用 `--force`）

## 从Prometheus项目的迁移

本功能从 Prometheus 项目迁移而来，主要变化：

1. **存储方式**: 从SQLModel数据库改为JSON文件存储
2. **简化字段**: 移除了用户相关字段（user_id, is_working等）
3. **异步支持**: 移除了异步锁，简化为同步操作
4. **依赖减少**: 不依赖FastAPI和SQLModel
5. **管理工具**: 新增了命令行管理工具

这些变化使得功能更轻量级，更适合Bug-Reproduction-Agent项目的需求。
