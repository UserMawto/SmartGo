---
name: "smartgo"
description: "Task orchestration skill that auto-routes coding tasks by difficulty, selects execution mode (ReAct/Plan&Execute/Reflection), enforces safety guards against infinite loops, applies tiered Ponytail code constraints, and tracks token savings. Invoke when receiving any coding task that needs execution planning, or when user sends smartgo:* commands."
---

# Skill: SmartGo 智跑

## 目标

拿到编码任务自动判断难度，自动选合适干活方式；内置马尾辫(Ponytail)精简代码约束；大任务按需启用 Superpowers 全套工程流程；防止任务卡死、无限死循环；控制 token 花钱；输出每一步真实消耗+预估省下多少 token。

只做上层调度管控，不替换底层工具能力。

## 全局配置（支持用户输入指令直接改）

```yaml
smartgo:
  run_mode: safe_auto      # 可选 semi｜strict_auto｜safe_auto
  log_level: summary       # step｜summary｜off
  telemetry:
    calc_token_saved: true
    save_log_to_file: false
  safety:
    max_all_round: 30
    max_one_subtask_round: 10
    token_max_budget: 150000
  superpowers:
    auto_open_token: 120000
    danger_task_token: 200000
```

### run_mode 三种运行模式（人话解释）

1. `semi` 半自动
普通使用，遇到大型任务、token 快要超预算，**主动问你确认，再继续往下跑**。

2. `strict_auto` 纯全自动
夜间跑任务、批量执行用，**全程绝不问人**；任务复杂度超标直接降级；碰到保护上限直接停止，输出完整报告。

3. `safe_auto` 安全自动【默认，最亲民】
大部分任务自动跑完不用管；
**只有碰到超高风险的巨型重构/全仓改造，就算开自动，也停下来问你确认**，避免偷偷烧掉大量 token。

> 用户快捷控制指令（直接发给 Agent）
> `smartgo:fast` 快速模式，简单干活，不走复杂流程
> `smartgo:full_project` 强制开启 Superpowers 完整项目流程
> `smartgo:run_mode=semi/strict_auto/safe_auto` 切换运行模式

---

## Layer1 任务难度判断（入口第一步）

接收用户任务，判断难度，打上标签，输出 `[SmartGo 判断：xxx]`

标签列表：

- `tiny_fix`：小改动，改配置、单文件修 bug、小脚本
- `normal_feature`：普通功能，少量文件改动
- `big_project`：大型功能项目，多模块开发
- `danger_task` 高危任务（满足任意就打上）
  1. 预估 token 超过 danger_task_token
  2. 改动文件超过 30 个、整个仓库重构、从零搭建整套系统
  3. 需要启动 4 个以上子代理，大量 git 分支操作
- `explore_debug` 调研排错，容易死循环

---

## Layer2 自动匹配干活模式

根据上面难度标签自动选择执行方式，可以被用户指令强制覆盖。

1. **ReAct 快速模式** → `tiny_fix`
   简单思考-调用工具-输出结果，不搞复杂规划，速度快。

2. **计划执行 Plan&Execute** → `normal_feature`
   先输出简单计划，拆小任务逐个执行，每个子任务做完简单校验，不强制全套 TDD。

3. **计划+自省 Plan&Execute+Reflection** → `big_project` / `explore_debug`
   做计划，执行子任务，每轮做完自我检查，发现偏差修正计划。
   - `explore_debug` 默认走此模式，**禁止启用 Superpowers**，调研排错不需要重型工程流程，避免浪费 token。

### Superpowers 触发逻辑（重要：不默认开启）

Superpowers 包含完整 TDD、子代理、git worktree、PR 交付流程，重量级，消耗大量 token。

1. 只有标签 `big_project` 并且 token 预算达标（≤ `auto_open_token`）才考虑开启。
2. `explore_debug` **禁止启用 Superpowers**。
3. 如果命中 `danger_task`，按照 run_mode 规则决定是否询问用户：
   - `semi`：询问用户确认
   - `safe_auto`：**即使自动模式，也要停下来询问确认**
   - `strict_auto`：不询问，直接降级，放弃 Superpowers，回退 Plan&Execute+Reflection
4. 用户可以指令强制：`smartgo:full_project` 强制开启 Superpowers。

### Git 安全规则

全自动模式下，Superpowers 仅创建本地分支，**禁止推送远程 git、禁止自动创建远程 PR**，只输出 PR 文本报告。

---

## Layer3 安全防护层（全部模式强制生效，防卡死死循环）

所有模式都强制执行这一层，不会被关闭：

1. **全局总轮次上限** + **单个子任务独立轮次上限**；到达上限直接终止任务，输出已有成果与未完成清单。
2. **Token 预算监控**，快到阈值触发告警；`strict_auto` 模式直接终止，`semi` 模式询问。
3. **死循环识别**：连续多轮思考、工具调用高度重复，立刻中断，输出诊断信息。
4. **长任务阶段性输出进度**（通过 Layer5 观测层实时输出），避免黑盒卡死。

---

## Layer4 马尾辫 Ponytail 分级约束（避免过度写垃圾冗余代码）

根据任务难度自动切换强度，解决原生 Ponytail 三大缺陷：
- 原生缺陷 1：仅适合 CRUD/简单业务，复杂算法、底层组件无收益
- 原生缺陷 2：已极简代码几乎无收益
- 原生缺陷 3：只改变生成逻辑，不替代安全审计、单元测试

| 任务标签 | Ponytail 等级 | 行为说明 |
|---|---|---|
| `tiny_fix` | `full` | 最大精简，优先标准库原生 API，拒绝多余依赖 |
| `normal_feature` | `lite` | 抑制过度封装，允许合理抽象 |
| `big_project`（开启 Superpowers） | `off` | 关闭 Ponytail 强制约束，交由 Superpowers 双层 Review 管控 |

> 禁止一刀切永远 full；大项目不会被过度保守限制。
> `explore_debug` 默认使用 `lite` 等级。

### Layer4 与 Layer2 独立解耦（重要）
> Ponytail（Layer4）和 Superpowers（Layer2）是**两个独立的层，不耦合**。
>
> | 层 | 管什么 | 不管什么 |
> |---|---|---|
> | Layer4 Ponytail | 代码风格、依赖选择、输出量、扫描深度 | 不管 TDD/CI/测试验证 |
> | Layer2 Superpowers | TDD 验证、CI 配置、覆盖率分析、工程文件 | 不管代码风格/依赖选择 |
>
> `ponytail=off` 只意味着"解除代码风格约束"，**不会自动触发** Superpowers 的 TDD/CI/覆盖率行为。Superpowers 由 Layer2 独立控制开关。
>
> 场景执行器适配详见 [PONYTAIL_SPEC.md](PONYTAIL_SPEC.md)。

---

## Layer5 观测日志｜贯穿全程的独立观测层（非终点输出）

> **核心定位**：Layer5 是一个独立运行、贯穿所有环节的持续观测层，**不是只在任务结束时才输出**。
> 从 Layer1 任务分类开始，到 Layer2 模式调度、Layer3 安全监控、Layer4 代码约束，每一层每一步都在持续采集数据、按配置粒度实时输出。

配置 `calc_token_saved: true` 开启。

> ⚠️ 所有"预估节省"标注：【参考估算，非精确计费】

### 贯穿各层的观测点

| 观测时机 | 所在层 | 输出内容 |
|---|---|---|
| 任务分类完成 | Layer1 | `[SmartGo 判断：xxx]` + 预估 token 区间 + 已选执行模式 |
| 模式切换/降级 | Layer2 | 模式变更原因 + 降级触发（如自动降级未启用 Superpowers） |
| 安全保护触发 | Layer3 | 轮次计数 + token 预算剩余 + 死循环检测告警 + 进度快照 |
| 子任务/轮次完成 | 各层 | 当前轮 token 真实消耗 + 累计消耗 + 预估节省累计 |
| 任务最终结束 | 全程汇总 | 完整 SmartGo 执行报告（见下方模板） |

### 预估节省三大来源

> ⚠️ 所有【预估节省】任何输出场景必须带上标注 `【参考估算，非精确计费】`，防止把预估值当成账单。

1. **Ponytail 代码精简**带来输出 token 节省：按等级使用经验系数估算
2. **模式自适应节省**：避免错误启用重型 Superpowers 流程带来的开销
3. **安全保护层拦截**：拦截死循环无效轮次，规避潜在消耗

```
# 估算系数参考（仅供内部计算，不对外作为计费）
# ponytail=full  completion 节省系数：0.75-0.90
# ponytail=lite  completion 节省系数：0.30-0.50
# ponytail=off   节省系数：0（无节省）
# 模式避免Superpowers 节省系数：0.60-0.80
# 安全拦截死循环    节省系数：0.80-0.95
```

### 日志粒度

1. `step`：每个子任务每一轮都输出日志，适合调试
2. `summary`（默认）：在模式切换、子任务组完成、触发安全保护、任务结束输出汇总
3. `off`：关闭日志

> 无论哪种粒度，安全保护触发和任务终止时**必须输出当前全部统计**，不丢失数据。

### 贯穿式日志输出示例

```
# Layer1 完成时
[SmartGo 观测] 任务标签：normal_feature | 预估token：~30k | 已选模式：Plan&Execute | ponytail=lite

# Layer2 模式切换/降级时
[SmartGo 观测] 模式切换：Plan&Execute → 降级未启用Superpowers | 原因：预估token超出auto_open_token | 预估避免消耗~80k token

# Layer3 安全触发时
[SmartGo 观测] 安全告警：轮次12/30 | token消耗48k/150k | 死循环检测：正常 | 进度：3/5子任务完成

# 每轮/子任务完成时（summary粒度）
[SmartGo 观测] 子任务2完成 | 本轮消耗：输入3.2k/输出1.8k | 累计：输入9.6k/输出5.4k | 预估节省累计：~12k token
```

### 任务结束输出完整报告模板

```
======== SmartGo 执行报告 ========
运行模式：xxx
Superpowers：开启/未开启
马尾辫强度：xxx
总运行轮次：xx
【真实消耗】
输入token：xxx 输出token：xxx 合计：xxx
【预估节省(仅供参考)】
👉 精简代码节省：xxx
👉 模式选轻量避免重型流程节省：xxx
👉 拦截无效循环避免消耗：xxx
✅ 预估一共省下token：xxx
安全触发：无/xxx
任务标签：xxx
===================================
```

### 特殊场景日志

1. 自动降级不启用 Superpowers 时，单独日志标记：`[自动降级]超出预算，未启用Superpowers，预估避免消耗xxx token`
2. 任务被安全机制强制终止，依然输出当前全部统计，不丢失数据。

---

## 硬性规则

1. **用户强制指令优先级高于一切自动判断**。`smartgo:fast` / `smartgo:full_project` 优先级高于任务分类、高于 run_mode 配置。
2. 日志统计模块只输出信息，**绝不干预执行逻辑，统计出错不打断主任务**。
3. `strict_auto` 纯全自动模式：就算是 danger_task 高危任务，也不会询问，直接降级。
4. `safe_auto` 安全自动模式：命中 danger_task 高危任务，**强制打断，等待用户确认**。
5. 全自动模式下 Superpowers 仅生成本地分支，禁止自动推送远程 git、自动创建远程 PR，只输出 PR 文本报告。
6. 所有【预估节省】任何输出场景必须带上标注 `【参考估算，非精确计费】`，防止把预估值当成账单。

---

## 完整执行时序

> Layer5 观测层贯穿以下每一步，不是最后才启动。每一步完成都会按日志粒度输出对应观测信息。

1. 用户下发编码任务 → **Layer5 开始采集** → 送入 Layer1 任务分类器，输出任务标签 → Layer5 输出分类观测
2. 根据标签 + `run_mode` 配置，Layer2 选择执行模式；判定是否允许启用 Superpowers；高危任务按规则选择是否询问用户 → Layer5 输出模式选择/降级观测
3. 进入选中执行模式运行；**全程 Layer3 安全保护层持续监控** → Layer5 每轮输出安全状态观测
4. 每一轮输出代码，Layer4 Ponytail 分级约束生效 → Layer5 输出本轮 token 消耗 + 预估节省累计
5. 任务完成 / 触发安全保护终止 → Layer5 输出完整 SmartGo 执行报告（全程数据汇总）

---

## 边界约束 & 取舍设计

1. **Superpowers 绝不默认打开**：解决原生 Superpowers 小任务小题大做、token 爆炸。
2. **Ponytail 分级而非一刀切**：解决原生 Ponytail 复杂项目过度保守的短板。
3. **安全层独立，和业务逻辑解耦**：无论使用哪种执行模式，防卡死、防死循环强制生效。
4. **全自动区分普通大任务和高危任务**：safe_auto 模式下，巨型重构即使全自动也要确认；strict_auto 完全无人值守直接降级。
5. **Git 操作安全隔离**：全自动禁止改动远程仓库，避免误提交。
6. **观测层只做输出，不干预业务**，保障主流程稳定性。

---

## 项目结构（v2.0 — 主链路与场景分离）

```
smartgo/
├── SKILL.md                Agent 提示词指令
├── config.yaml             默认配置
├── requirements.txt        Python 依赖
├── smartgo/                Python 包
│   ├── __init__.py         统一导出 core + scenarios
│   ├── cli.py              CLI 转发入口
│   │
│   ├── core/               主链路（独立文件夹，不依赖场景）
│   │   ├── config.py       配置管理
│   │   ├── classifier.py   Layer1 任务分类器
│   │   ├── router.py       Layer2 执行模式调度
│   │   ├── safety.py       Layer3 安全防护
│   │   ├── ponytail.py     Layer4 分级约束
│   │   ├── telemetry.py    Layer5 观测日志
│   │   ├── orchestrator.py 主调度器
│   │   └── cli.py          CLI 入口（所有子命令）
│   │
│   └── scenarios/          场景执行器（按场景各自独立文件夹）
│       ├── crawler/        爬虫场景（爬取+清洗+导出）
│       ├── code_fix/       修bug场景（模式扫描+修复）
│       ├── test/           测试场景（pytest/unittest+覆盖率）
│       ├── scaffold/       脚手架场景（3种模板项目生成）
│       └── audit/          项目审计场景（5维度项目体检）
```

**依赖方向**：`scenarios/* → core/`（单向），core 不依赖 scenarios。加新场景不影响主链路。

---

## 内置场景执行器

SmartGo 是通用调度管控系统，不限于特定场景。以下内置执行器可直接通过 CLI 使用，也可传自定义 `subtask_executor` 处理任何任务：

| 执行器 | 路径 | 任务标签 | 能力 |
|---|---|---|---|
| 爬虫 | `scenarios/crawler/` | tiny_fix~normal_feature | 请求重试、限速、反检测、HTML解析、数据清洗、JSON/CSV导出 |
| 修bug | `scenarios/code_fix/` | tiny_fix | 5种bug模式扫描（bare except/可变默认/f-string/SQL注入/None检查）+自动修复 |
| 测试 | `scenarios/test/` | normal_feature | pytest/unittest执行、结果解析、覆盖率分析 |
| 脚手架 | `scenarios/scaffold/` | danger_task | 3种模板（Web/CLI/Package），自动生成项目结构+git init |
| 审计 | `scenarios/audit/` | explore_debug | 安全扫描、代码异味、项目健康、依赖检查、最佳实践覆盖率，输出评级A-F |

> Agent 也可传自定义 `subtask_executor` 回调处理任何任务类型，五层调度架构对所有场景统一生效。

---

## CLI 命令

```bash
# 通用调度
smartgo classify "任务描述"                          # 仅分类，不执行
smartgo run "任务描述" --subtasks "步骤1,步骤2"       # 通用执行
smartgo command smartgo:fast                         # 切换快速模式
smartgo status                                       # 查看状态
smartgo config                                       # 查看配置

# 内置执行器
smartgo crawl "https://example.com" --max-pages 50  # 爬虫
smartgo fix app.py --description "TypeError"        # 修bug
smartgo test tests/ --coverage                      # 跑测试
smartgo scaffold my_project --template python_web  # 脚手架
smartgo audit /path/to/project                      # 项目审计
```

### 用户快捷指令

> `smartgo:fast` 强制 ReAct 快速模式
> `smartgo:full_project` 强制开启 Superpowers
> `smartgo:run_mode=semi/strict_auto/safe_auto` 切换运行模式
