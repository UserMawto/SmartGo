# SmartGo 场景执行器 Ponytail & Superpowers 适配规范

> Layer4 (Ponytail) 和 Layer2 (Superpowers) 是两个独立的层，不耦合。
> 所有场景执行器必须分别适配两者。

## 两层职责划分

| 层 | 职责 | 控制什么 |
|---|---|---|
| Layer4 Ponytail | 代码风格/依赖选择/输出量 | 用不用标准库、输出多详细、扫描多深 |
| Layer2 Superpowers | 工程流程 | TDD、CI配置、测试验证、覆盖率分析、PR流程 |

**核心原则：两层独立配置，不耦合**

```
tiny_fix       → ponytail=full,  superpowers=disable
normal_feature → ponytail=lite,  superpowers=disable
big_project    → ponytail=off,   superpowers=enable (如果token达标)
```

## Layer4 Ponytail 三级定义

| 等级 | 代码风格 | 依赖 | 输出 |
|---|---|---|---|
| full | 极致精简 | 标准库优先，拒绝多余依赖 | 最小输出 |
| lite | 适度约束 | 允许合理外部依赖 | 标准输出 |
| off | 不限制 | 不限制 | 不限制 |

## Layer2 Superpowers 开关

| 状态 | 行为 |
|---|---|
| enabled | TDD验证、CI配置、覆盖率分析、Makefile/CHANGELOG 等工程文件 |
| disabled | 不走重型工程流程 |

## 适配模板

### 1. 构造函数接收两个独立参数

```python
class MyExecutor:
    def __init__(self, ponytail_level: str = "lite",
                 superpowers_enabled: bool = False):
        self.ponytail_level = ponytail_level
        self.superpowers_enabled = superpowers_enabled
```

### 2. 核心方法中两层分别控制

```python
def execute(self, ...):
    # Layer4 Ponytail: 控制代码风格/依赖/输出量
    if self.ponytail_level == "full":
        # 标准库，最小输出
        ...
    elif self.ponytail_level == "lite":
        # 允许外部依赖，标准输出
        ...
    # off: 不限制

    # Layer2 Superpowers: 控制工程流程（完全独立）
    if self.superpowers_enabled:
        # TDD验证、CI配置、覆盖率分析
        ...
```

### 3. as_subtask_executor 从 prompt 分别提取

```python
def as_subtask_executor(self):
    def executor(subtask_name: str, ponytail_prompt: str) -> SubtaskResult:
        # Layer4 等级
        if "Ponytail=full" in ponytail_prompt:
            self.ponytail_level = "full"
        elif "Ponytail=off" in ponytail_prompt:
            self.ponytail_level = "off"
        else:
            self.ponytail_level = "lite"

        # Layer2 Superpowers 状态
        self.superpowers_enabled = "Superpowers=on" in ponytail_prompt
```

## 现有场景适配对照表

| 场景 | Ponytail 控制的 | Superpowers 控制的 |
|---|---|---|
| crawler | urllib vs requests, re vs bs4 | （暂无） |
| code_fix | 只扫描 vs 扫描+修复 | 修复后跑测试验证 |
| test_runner | 输出量（总数/详情/原始日志） | 覆盖率分析 |
| scaffold | 文件范围（最小/标准） | CI+Makefile+CHANGELOG |
| audit | 扫描深度（安全only/标准） | 最佳实践覆盖率 |

## 新增场景检查清单

- [ ] 构造函数接收 `ponytail_level` 和 `superpowers_enabled` 两个独立参数
- [ ] Ponytail 只控制代码风格/依赖选择/输出量
- [ ] Superpowers 只控制工程流程（TDD/CI/验证/覆盖率）
- [ ] `as_subtask_executor` 分别从 prompt 提取两个信号
- [ ] 两层不耦合：ponytail=off 不自动触发 Superpowers 行为
- [ ] 文档标注两层各自的行为差异

## 反模式（禁止）

1. **两层耦合**：ponytail=off 自动触发 TDD/CI（应由 superpowers 独立控制）
2. **Ponytail 管工程流程**：在 ponytail 等级里做 CI 配置/测试验证
3. **Superpowers 管代码风格**：在 superpowers 里限制依赖选择
4. **不提取 Superpowers 信号**：as_subtask_executor 只提取 ponytail 等级，忽略 Superpowers
