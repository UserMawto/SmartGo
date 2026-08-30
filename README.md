# SmartGo 智跑 v2.0

通用任务调度管控 Skill — 自动判断难度、选执行模式、防死循环、省 token。

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 分类一个任务（不执行）
python3 -m smartgo.cli classify "修复登录页面的CSS bug" --files 1 --token 2000

# 执行一个任务
python3 -m smartgo.cli run "重构认证模块" --subtasks "分析现状,拆分接口,更新调用方" --files 5 --token 15000

# 审计一个项目
python3 -m smartgo.cli audit /path/to/project

# 查看状态
python3 -m smartgo.cli status
```

## 五层架构

| 层 | 模块 | 职责 |
|---|---|---|
| Layer1 | 任务分类器 | 判断难度，输出标签（tiny_fix/normal_feature/big_project/danger_task/explore_debug） |
| Layer2 | 执行模式调度 | 自动选 ReAct / Plan&Execute / Plan&Execute+Reflection，按需启用 Superpowers |
| Layer3 | 安全防护 | 轮次上限、token 预算、死循环检测、进度输出（强制生效） |
| Layer4 | Ponytail 约束 | 分级代码精简（full/lite/off），避免过度冗余或过度保守 |
| Layer5 | 观测日志 | 贯穿全程，真实消耗 + 预估节省 token，分 step/summary/off 粒度 |

## 目录结构

```
smartgo/
├── SKILL.md                    Agent 提示词
├── config.yaml                 默认配置
├── requirements.txt            依赖
└── smartgo/                    Python 包
    ├── __init__.py             统一导出
    ├── cli.py                  CLI 转发入口
    ├── core/                   主链路（不依赖场景）
    │   ├── config.py           配置管理
    │   ├── classifier.py       Layer1 分类器
    │   ├── router.py            Layer2 路由
    │   ├── safety.py            Layer3 安全防护
    │   ├── ponytail.py          Layer4 约束
    │   ├── telemetry.py         Layer5 观测
    │   ├── orchestrator.py      主调度器
    │   └── cli.py               CLI 入口
    └── scenarios/              场景执行器（各自独立）
        ├── crawler/            爬虫 + 数据清洗
        ├── code_fix/           bug 模式扫描 + 修复
        ├── test/               测试执行 + 覆盖率
        ├── scaffold/           项目脚手架生成
        └── audit/              项目审计（5维度）
```

**依赖方向**：`scenarios/* → core/`（单向）。加新场景不影响主链路。

## CLI 命令

### 通用调度

| 命令 | 说明 |
|---|---|
| `smartgo classify "任务" --files N --token T` | 仅分类，不执行 |
| `smartgo run "任务" --subtasks "步骤1,步骤2"` | 通用执行 |
| `smartgo command smartgo:fast` | 切换快速模式 |
| `smartgo status` | 查看状态 |
| `smartgo config` | 查看配置 |

### 内置执行器

| 命令 | 说明 |
|---|---|
| `smartgo crawl "url" --max-pages 50` | 爬虫（重试+限速+反检测+清洗+导出） |
| `smartgo fix file.py --description "bug"` | 修bug（5种模式扫描+修复） |
| `smartgo test tests/ --coverage` | 跑测试（pytest/unittest+覆盖率） |
| `smartgo scaffold name --template python_web` | 脚手架（Web/CLI/Package 模板） |
| `smartgo audit /path/to/project` | 项目审计（安全/异味/健康/依赖/实践） |

### 快捷指令

| 指令 | 说明 |
|---|---|
| `smartgo:fast` | 强制 ReAct 快速模式 |
| `smartgo:full_project` | 强制开启 Superpowers |
| `smartgo:run_mode=semi/strict_auto/safe_auto` | 切换运行模式 |

## 运行模式

| 模式 | 说明 |
|---|---|
| `safe_auto`（默认） | 普通任务自动跑；命中 danger_task 强制暂停问人 |
| `semi` | 大任务/超预算都问人确认 |
| `strict_auto` | 全程不问人；高危任务直接降级；触发保护直接终止 |

## 配置

编辑 `config.yaml`：

```yaml
smartrun:
  run_mode: safe_auto
  log_level: summary
  telemetry:
    calc_token_saved: true
  safety:
    max_all_round: 30
    max_one_subtask_round: 10
    token_max_budget: 150000
  superpowers:
    auto_open_token: 120000
    danger_task_token: 200000
```

## Python API

```python
from smartgo import SmartGoOrchestrator, SmartGoConfig

config = SmartGoConfig()
orchestrator = SmartGoOrchestrator(config)

# 自定义执行器
def my_executor(subtask_name, ponytail_prompt):
    # 你的业务逻辑
    return SubtaskResult(name=subtask_name, success=True, ...)

result = orchestrator.run(
    task_description="重构认证模块",
    subtask_executor=my_executor,
    subtask_names=["分析现状", "拆分接口", "更新调用方"],
)
```

### 使用内置执行器

```python
from smartgo import CodeFixer, TestRunner, ProjectAuditor

# 修bug
task = CodeFixer.build_task("app.py", "TypeError on line 42")
result = SmartGoOrchestrator(SmartGoConfig()).run(**task)

# 跑测试
task = TestRunner.build_task("tests/", run_coverage=True)
result = SmartGoOrchestrator(SmartGoConfig()).run(**task)

# 项目审计
auditor = ProjectAuditor()
report = auditor.audit("/path/to/project")
print(f"评级：{report.grade}")
print(f"问题总数：{report.total_issues}")
```

## 安全防护

所有执行模式强制生效：

- 全局轮次上限（默认 30）+ 子任务轮次上限（默认 10）
- Token 预算监控（默认 150k），超限触发告警/终止
- 死循环检测：连续多轮重复工具调用，立即中断
- 长任务阶段性进度输出，避免黑盒卡死
- 全自动模式禁止推送远程 git / 创建远程 PR

## 审计维度

`smartgo audit` 检查 5 个维度，输出 A-F 评级：

| 维度 | 检查项 |
|---|---|
| 安全 | 硬编码密钥、SQL注入、eval/exec、pickle.load、DEBUG=True |
| 代码异味 | 函数过长、嵌套过深、参数过多、文件过大、行过长 |
| 项目健康 | README/.gitignore/requirements.txt 存在性、CI 配置、测试目录 |
| 依赖 | 声明了没用、用了没声明 |
| 最佳实践 | Type Hint 覆盖率、Docstring 覆盖率 |

## License

MIT
