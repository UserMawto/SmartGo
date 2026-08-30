"""SmartGo Layer4 马尾辫 Ponytail 分级约束层

根据任务难度动态切换 Ponytail 强度，解决原生 Ponytail 三大缺陷。
"""

from dataclasses import dataclass
from typing import List

from .config import TaskLabel


@dataclass
class PonytailRule:
    level: str  # full | lite | off
    prefer_stdlib: bool = False
    reject_external_deps: bool = False
    suppress_overengineering: bool = False
    allow_reasonable_abstraction: bool = False
    enforce_max_conciseness: bool = False
    description: str = ""


class PonytailConstraint:
    """Layer4: 分级代码精简约束"""

    # 各等级规则
    LEVEL_RULES = {
        "full": PonytailRule(
            level="full",
            prefer_stdlib=True,
            reject_external_deps=True,
            suppress_overengineering=True,
            enforce_max_conciseness=True,
            allow_reasonable_abstraction=False,
            description="最大精简：优先标准库原生API，拒绝多余依赖、冗余代码",
        ),
        "lite": PonytailRule(
            level="lite",
            prefer_stdlib=True,
            reject_external_deps=False,
            suppress_overengineering=True,
            enforce_max_conciseness=False,
            allow_reasonable_abstraction=True,
            description="适度约束：抑制过度封装，允许合理抽象",
        ),
        "off": PonytailRule(
            level="off",
            prefer_stdlib=False,
            reject_external_deps=False,
            suppress_overengineering=False,
            enforce_max_conciseness=False,
            allow_reasonable_abstraction=True,
            description="关闭约束：交由 Superpowers 双层 Review 管控",
        ),
    }

    # 原生 Ponytail 三大缺陷
    PONYTAIL_LIMITATIONS = [
        "仅适合CRUD/简单业务，复杂算法、底层组件无收益",
        "已极简代码几乎无收益",
        "只改变生成逻辑，不替代安全审计、单元测试",
    ]

    LABEL_TO_LEVEL = {
        TaskLabel.TINY_FIX: "full",
        TaskLabel.NORMAL_FEATURE: "lite",
        TaskLabel.BIG_PROJECT: "off",
        TaskLabel.DANGER_TASK: "off",
        TaskLabel.EXPLORE_DEBUG: "lite",
    }

    def __init__(self):
        self.current_level: str = "lite"
        self.current_rule: PonytailRule = self.LEVEL_RULES["lite"]

    def apply(self, label: TaskLabel):
        """根据任务标签切换 Ponytail 强度"""
        level = self.LABEL_TO_LEVEL.get(label, "lite")
        self.current_level = level
        self.current_rule = self.LEVEL_RULES[level]

    def set_level(self, level: str):
        """手动设置等级"""
        if level in self.LEVEL_RULES:
            self.current_level = level
            self.current_rule = self.LEVEL_RULES[level]

    def check_code(self, code: str, dependencies: List[str] = None) -> dict:
        """检查代码是否符合当前 Ponytail 约束

        返回 {passed: bool, violations: [str], suggestions: [str]}
        """
        result = {"passed": True, "violations": [], "suggestions": []}
        deps = dependencies or []

        if self.current_level == "off":
            return result

        rule = self.current_rule

        # 检查外部依赖
        if rule.reject_external_deps and deps:
            stdlib_prefixes = ("os", "sys", "json", "re", "pathlib", "typing",
                             "dataclasses", "enum", "collections", "itertools",
                             "functools", "abc", "io", "math", "datetime",
                             "hashlib", "subprocess", "argparse", "logging")
            external = [d for d in deps if not d.split(".")[0] in stdlib_prefixes]
            if external:
                result["violations"].append(
                    f"full模式拒绝外部依赖：{external}，请使用标准库替代"
                )
                result["passed"] = False

        # 检查过度封装（简单启发式）
        if rule.suppress_overengineering:
            # 检测空抽象层：只有一个方法的抽象类
            if "abstractmethod" in code and code.count("def ") <= 2:
                result["suggestions"].append(
                    "检测到可能过度封装的抽象类，考虑直接用函数替代"
                )

            # 检测无意义的代理/包装
            if "class " in code and "def __init__" in code and code.count("def ") <= 3:
                if "self._" in code and "pass" in code:
                    result["suggestions"].append(
                        "检测到可能无意义的包装类，考虑精简"
                    )

        # 检查极致精简
        if rule.enforce_max_conciseness:
            # 过长函数检测
            lines = [l for l in code.split("\n") if l.strip() and not l.strip().startswith("#")]
            if len(lines) > 50:
                result["suggestions"].append(
                    f"函数过长({len(lines)}行)，full模式建议拆分或精简"
                )

        if result["violations"]:
            result["passed"] = False

        return result

    def get_constraint_prompt(self) -> str:
        """输出当前 Ponytail 约束的提示词，供 Agent 参考"""
        rule = self.current_rule
        parts = [f"[SmartGo Ponytail={rule.level}] {rule.description}"]

        if rule.level == "off":
            parts.append("当前关闭Ponytail约束，代码质量交由Superpowers双层Review管控")
            parts.append("（规避原生Ponytail缺陷：复杂算法/底层组件无收益、不替代安全审计和测试）")
        else:
            if rule.prefer_stdlib:
                parts.append("- 优先使用标准库原生API")
            if rule.reject_external_deps:
                parts.append("- 拒绝引入多余外部依赖")
            if rule.suppress_overengineering:
                parts.append("- 抑制过度封装和无意义抽象层")
            if rule.enforce_max_conciseness:
                parts.append("- 追求极致精简，拒绝冗余代码")
            if rule.allow_reasonable_abstraction:
                parts.append("- 允许合理的封装和抽象")

        return "\n".join(parts)
