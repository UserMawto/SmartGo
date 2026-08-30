# SmartGo 场景执行器 Ponytail 适配规范

> 所有内置场景执行器必须遵循此规范。新增场景时照此实现，确保 Ponytail 分级在所有场景统一生效。

## 核心原则

SmartGo 的 Layer4 Ponytail 分级约束不是可选的——**每个场景执行器必须根据 ponytail_level 切换行为**。等级由 Layer1 任务分类器自动判定，通过 `ponytail_prompt` 字符串传递给执行器。

## 三级定义

| 等级 | 对应任务标签 | 设计意图 | 代码风格 |
|---|---|---|---|
| `full` | tiny_fix | 极致精简，最小改动，拒绝额外依赖 | 只用标准库，不引入新依赖 |
| `lite` | normal_feature | 合理抽象，适度约束，允许额外库 | 允许合理封装和外部依赖 |
| `off` | big_project | 自由选择，交由 Superpowers 评审管控 | 不限制，用最好的工具 |

## 适配模板

每个场景执行器必须实现以下结构：

### 1. 构造函数接收 ponytail_level

```python
class MyExecutor:
    def __init__(self, ponytail_level: str = "lite"):
        self.ponytail_level = ponytail_level
```

### 2. 核心方法按等级切换行为

```python
def execute(self, ...):
    # 所有等级都执行的基础逻辑
    self._do_basic_work()

    # ponytail=full：到此为止，不深入
    if self.ponytail_level == "full":
        return result

    # ponytail=lite：标准处理
    self._do_standard_work()

    # ponytail=off：完整深度处理
    if self.ponytail_level == "off":
        self._do_deep_work()
```

### 3. as_subtask_executor 从 ponytail_prompt 提取等级

```python
def as_subtask_executor(self):
    def executor(subtask_name: str, ponytail_prompt: str) -> SubtaskResult:
        # 从 prompt 提取等级（所有场景必须包含这段）
        if "Ponytail=full" in ponytail_prompt:
            self.ponytail_level = "full"
        elif "Ponytail=off" in ponytail_prompt:
            self.ponytail_level = "off"
        else:
            self.ponytail_level = "lite"

        # 执行子任务...
```

### 4. 输出按等级控制量

```python
def _print_summary(self, result):
    print(f"基础信息")           # 所有等级都输出

    if self.ponytail_level == "full":
        return                  # full：只输出基础信息

    print(f"标准详情")          # lite/off 输出

    if self.ponytail_level == "off":
        print(f"深度分析")      # off 额外输出
```

## 现有场景适配对照表

| 场景 | full（tiny_fix） | lite（normal_feature） | off（big_project） |
|---|---|---|---|
| **crawler** | urllib + re（标准库） | requests + beautifulsoup4 | requests + beautifulsoup4 |
| **code_fix** | 只扫描报告，不改文件 | 扫描 + 自动修复 | 扫描 + 修复 + 跑测试验证 |
| **test** | 最小输出（通过/失败总数） | 标准输出 + 失败详情 | 完整输出 + 覆盖率 + 原始日志 |
| **scaffold** | 最小结构（仅核心文件） | 标准结构（README+tests+config） | 完整结构（+CI+Makefile+CHANGELOG） |
| **audit** | 只扫安全漏洞 | 安全+异味+健康+依赖 | 全 5 维度+最佳实践覆盖率 |

## 新增场景检查清单

新增场景执行器时，逐项检查：

- [ ] 构造函数接收 `ponytail_level` 参数，默认 `"lite"`
- [ ] 核心方法按 `full`/`lite`/`off` 切换行为深度
- [ ] `full`：最小化输出、最小化副作用、只用标准库
- [ ] `lite`：标准处理 + 合理的外部依赖
- [ ] `off`：完整深度处理 + 验证/覆盖率等质量保障
- [ ] `as_subtask_executor` 包含 ponytail_prompt 提取逻辑
- [ ] 输出/日志按等级控制量
- [ ] 文档中标注三级行为差异

## 反模式（禁止）

1. **忽略 ponytail_level**：所有等级都做一样的深度处理
2. **full 不够精简**：full 模式仍然引入额外依赖或做深度分析
3. **off 不够深入**：off 模式和 lite 一样，没有额外深度
4. **硬编码等级**：不从 ponytail_prompt 动态提取，写死某个等级
5. **输出不分级**：所有等级都输出完整日志，浪费 token
