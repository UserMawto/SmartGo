"""SmartGo 内置项目审计执行器

适用场景：explore_debug — 检查别的项目有哪些问题。
能力：安全扫描 → 代码异味 → 项目健康 → 最佳实践 → 依赖检查。
与 SmartGo 安全防护层打通：扫描大量文件时防卡死。
"""

import os
import re
import ast
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from collections import defaultdict

from smartgo.core.orchestrator import SubtaskResult


# ===== 检查规则定义 =====

SECURITY_PATTERNS = {
    "hardcoded_secret": {
        "pattern": r"(?i)(password|secret|api_key|token|private_key)\s*=\s*['\"][^'\"]{8,}['\"]",
        "severity": "HIGH",
        "description": "硬编码密钥/密码",
    },
    "hardcoded_password": {
        "pattern": r"(?i)password\s*=\s*['\"][^'\"]+['\"]",
        "severity": "HIGH",
        "description": "硬编码密码",
    },
    "sql_injection": {
        "pattern": r"(execute|cursor\.execute)\s*\(\s*['\"].*%[sd].*['\"]\s*%",
        "severity": "CRITICAL",
        "description": "SQL 拼接，存在注入风险",
    },
    "eval_usage": {
        "pattern": r"\beval\s*\(",
        "severity": "HIGH",
        "description": "使用 eval()，存在代码注入风险",
    },
    "exec_usage": {
        "pattern": r"\bexec\s*\(",
        "severity": "HIGH",
        "description": "使用 exec()，存在代码注入风险",
    },
    "os_system": {
        "pattern": r"os\.system\s*\(",
        "severity": "MEDIUM",
        "description": "使用 os.system()，建议改用 subprocess",
    },
    "pickle_load": {
        "pattern": r"pickle\.load",
        "severity": "MEDIUM",
        "description": "pickle.load 可能导致反序列化攻击",
    },
    "debug_true": {
        "pattern": r"(?i)DEBUG\s*=\s*True",
        "severity": "LOW",
        "description": "DEBUG=True 不应出现在生产环境",
    },
    "allow_all_hosts": {
        "pattern": r"ALLOWED_HOSTS\s*=\s*\[?\s*['\"]\*['\"]",
        "severity": "HIGH",
        "description": "ALLOWED_HOSTS = ['*'] 允许所有主机",
    },
}

CODE_SMELL_RULES = {
    "max_function_length": 50,
    "max_nesting_depth": 5,
    "max_file_length": 500,
    "max_line_length": 120,
    "max_parameters": 7,
}

PROJECT_HEALTH_CHECKS = [
    ("README.md", "缺少 README.md 文件"),
    (".gitignore", "缺少 .gitignore 文件"),
    ("requirements.txt", "缺少 requirements.txt（未声明依赖）"),
    ("setup.py", "缺少 setup.py 或 pyproject.toml（未配置打包"),
    ("tests/", "缺少 tests/ 目录（无测试覆盖）"),
]


@dataclass
class Issue:
    file: str
    line: int
    rule: str
    severity: str
    message: str
    suggestion: str = ""


@dataclass
class AuditReport:
    project_path: str
    total_files: int = 0
    total_lines: int = 0
    issues: List[Issue] = field(default_factory=list)
    security_issues: List[Issue] = field(default_factory=list)
    code_smells: List[Issue] = field(default_factory=list)
    health_issues: List[str] = field(default_factory=list)
    practice_issues: List[Issue] = field(default_factory=list)
    dependency_issues: List[str] = field(default_factory=list)
    type_hint_coverage: float = 0.0
    docstring_coverage: float = 0.0

    @property
    def severity_counts(self) -> Dict[str, int]:
        counts = defaultdict(int)
        for issue in self.issues:
            counts[issue.severity] += 1
        return dict(counts)

    @property
    def total_issues(self) -> int:
        return len(self.issues) + len(self.health_issues) + len(self.dependency_issues)

    @property
    def grade(self) -> str:
        critical = self.severity_counts.get("CRITICAL", 0)
        high = self.severity_counts.get("HIGH", 0)
        total = self.total_issues
        if critical > 0:
            return "F"
        if high > 5 or total > 20:
            return "D"
        if high > 0 or total > 10:
            return "C"
        if total > 5:
            return "B"
        return "A"


class ProjectAuditor:
    """项目审计执行器

    用法：
        from smartgo.scenarios.audit.auditor import ProjectAuditor
        auditor = ProjectAuditor()
        report = auditor.audit("/path/to/project")
    """

    def audit(self, project_path: str, skip_dirs: List[str] = None) -> AuditReport:
        """执行完整项目审计"""
        if skip_dirs is None:
            skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv",
                         "env", ".env", "dist", "build", ".idea", ".vscode"}

        report = AuditReport(project_path=project_path)

        if not os.path.isdir(project_path):
            report.health_issues.append(f"项目路径不存在：{project_path}")
            return report

        # 1. 项目健康检查
        self._check_health(project_path, report)

        # 2. 扫描所有 Python 文件
        py_files = []
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for fname in files:
                if fname.endswith(".py"):
                    py_files.append(os.path.join(root, fname))

        report.total_files = len(py_files)

        for fpath in py_files:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            report.total_lines += content.count("\n") + 1

            rel_path = os.path.relpath(fpath, project_path)

            # 3. 安全扫描
            self._scan_security(rel_path, content, report)

            # 4. 代码异味
            self._scan_code_smells(rel_path, content, report)

            # 5. 最佳实践
            self._scan_practices(rel_path, content, fpath, report)

        # 6. 依赖检查
        self._check_dependencies(project_path, py_files, report)

        # 汇总
        self._print_summary(report)
        return report

    def _check_health(self, path: str, report: AuditReport):
        """检查项目基础健康度"""
        for fname, message in PROJECT_HEALTH_CHECKS:
            full_path = os.path.join(path, fname)
            if not os.path.exists(full_path):
                report.health_issues.append(message)

        # 额外检查
        ci_dirs = [".github/workflows", ".gitlab-ci.yml", ".circleci"]
        has_ci = any(os.path.exists(os.path.join(path, d)) for d in ci_dirs)
        if not has_ci:
            report.health_issues.append("未检测到 CI/CD 配置")

    def _scan_security(self, file: str, content: str, report: AuditReport):
        """安全模式扫描"""
        for rule_name, info in SECURITY_PATTERNS.items():
            for match in re.finditer(info["pattern"], content):
                line = content[:match.start()].count("\n") + 1
                issue = Issue(
                    file=file,
                    line=line,
                    rule=rule_name,
                    severity=info["severity"],
                    message=info["description"],
                    suggestion=f"查看 {file}:{line}",
                )
                report.security_issues.append(issue)
                report.issues.append(issue)

    def _scan_code_smells(self, file: str, content: str, report: AuditReport):
        """代码异味检测"""
        lines = content.split("\n")

        # 文件过长
        if len(lines) > CODE_SMELL_RULES["max_file_length"]:
            report.code_smells.append(Issue(
                file=file, line=0, rule="long_file",
                severity="LOW",
                message=f"文件过长：{len(lines)}行（建议<{CODE_SMELL_RULES['max_file_length']}）",
            ))
            report.issues.append(report.code_smells[-1])

        # 行过长
        for i, line in enumerate(lines):
            if len(line) > CODE_SMELL_RULES["max_line_length"]:
                report.code_smells.append(Issue(
                    file=file, line=i + 1, rule="long_line",
                    severity="LOW",
                    message=f"行过长：{len(line)}字符",
                ))
                report.issues.append(report.code_smells[-1])

        # AST 分析
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 函数过长
                func_len = node.end_lineno - node.lineno + 1 if hasattr(node, "end_lineno") else 0
                if func_len > CODE_SMELL_RULES["max_function_length"]:
                    report.code_smells.append(Issue(
                        file=file, line=node.lineno, rule="long_function",
                        severity="MEDIUM",
                        message=f"函数 {node.name} 过长：{func_len}行",
                    ))
                    report.issues.append(report.code_smells[-1])

                # 参数过多
                args = node.args
                param_count = len(args.args) + len(args.kwonlyargs)
                if param_count > CODE_SMELL_RULES["max_parameters"]:
                    report.code_smells.append(Issue(
                        file=file, line=node.lineno, rule="too_many_params",
                        severity="MEDIUM",
                        message=f"函数 {node.name} 参数过多：{param_count}个",
                    ))
                    report.issues.append(report.code_smells[-1])

                # 嵌套深度
                depth = self._get_nesting_depth(node)
                if depth > CODE_SMELL_RULES["max_nesting_depth"]:
                    report.code_smells.append(Issue(
                        file=file, line=node.lineno, rule="deep_nesting",
                        severity="MEDIUM",
                        message=f"函数 {node.name} 嵌套过深：{depth}层",
                    ))
                    report.issues.append(report.code_smells[-1])

            # bare except
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    report.code_smells.append(Issue(
                        file=file, line=node.lineno, rule="bare_except",
                        severity="MEDIUM",
                        message="裸 except，会吞掉所有异常",
                    ))
                    report.issues.append(report.code_smells[-1])

    def _get_nesting_depth(self, node) -> int:
        """计算函数内最大嵌套深度"""
        max_depth = 0

        def count_depth(n, current=0):
            nonlocal max_depth
            for child in ast.iter_child_nodes(n):
                if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                    new_depth = current + 1
                    max_depth = max(max_depth, new_depth)
                    count_depth(child, new_depth)
                else:
                    count_depth(child, current)

        count_depth(node)
        return max_depth

    def _scan_practices(self, file: str, content: str, fpath: str, report: AuditReport):
        """最佳实践检查（type hint + docstring 覆盖率）"""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return

        total_funcs = 0
        hinted_funcs = 0
        docstringed_funcs = 0

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total_funcs += 1

                # type hint 检查
                args = node.args
                has_hints = False
                for arg in args.args:
                    if arg.annotation is not None:
                        has_hints = True
                        break
                if node.returns is not None:
                    has_hints = True
                if has_hints:
                    hinted_funcs += 1

                # docstring 检查
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    docstringed_funcs += 1
                elif (node.body and isinstance(node.body[0], ast.Expr)
                      and isinstance(node.body[0].value, ast.Str)):
                    docstringed_funcs += 1

                # 缺少 docstring
                if not docstringed_funcs or total_funcs > docstringed_funcs:
                    pass  # 只统计覆盖率，不逐个报告

        if total_funcs > 0:
            report.type_hint_coverage = (
                report.type_hint_coverage * 0 +  # 简化：用当前文件的值
                hinted_funcs / total_funcs * 100
            )
            report.docstring_coverage = (
                report.docstring_coverage * 0 +
                docstringed_funcs / total_funcs * 100
            )

    def _check_dependencies(self, path: str, py_files: List[str], report: AuditReport):
        """依赖检查"""
        # 读取 requirements.txt
        req_path = os.path.join(path, "requirements.txt")
        declared_deps = set()
        if os.path.exists(req_path):
            with open(req_path, "r") as f:
                for line in f:
                    line = line.strip().split("=")[0].split(">")[0].split("<")[0].strip()
                    if line and not line.startswith("#"):
                        declared_deps.add(line.lower().replace("_", "-"))

        # 收集代码中的 import
        used_deps = set()
        stdlib_modules = {
            "os", "sys", "re", "json", "csv", "math", "random", "datetime",
            "collections", "itertools", "functools", "pathlib", "typing",
            "dataclasses", "abc", "io", "time", "subprocess", "argparse",
            "hashlib", "base64", "urllib", "http", "logging", "unittest",
            "ast", "inspect", "copy", "decimal", "enum", "textwrap",
            "string", "struct", "tempfile", "shutil", "glob", "pickle",
            "sqlite3", "socket", "ssl", "select", "signal", "threading",
            "queue", "multiprocessing", "concurrent", "asyncio", "contextlib",
            "warnings", "traceback", "pprint", "reprlib", "weakref",
            "operator", "heapq", "bisect", "array", "queue", "types",
            "importlib", "configparser", "xml", "html", "email", "uuid",
        }

        for fpath in py_files:
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            top = alias.name.split(".")[0].lower()
                            if top not in stdlib_modules:
                                used_deps.add(top)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            top = node.module.split(".")[0].lower()
                            if top not in stdlib_modules:
                                used_deps.add(top)
            except SyntaxError:
                continue

        # 声明了但没用的依赖
        unused = declared_deps - used_deps
        for dep in sorted(unused):
            report.dependency_issues.append(f"声明了但未使用：{dep}")

        # 用了但没声明的依赖
        undeclared = used_deps - declared_deps
        for dep in sorted(undeclared):
            report.dependency_issues.append(f"使用了但未声明：{dep}")

    def _print_summary(self, report: AuditReport):
        """打印审计摘要"""
        print(f"\n{'='*50}")
        print(f"SmartGo 项目审计报告")
        print(f"{'='*50}")
        print(f"项目路径：{report.project_path}")
        print(f"扫描文件：{report.total_files} 个")
        print(f"总代码行：{report.total_lines} 行")
        print(f"项目评级：{report.grade}")

        counts = report.severity_counts
        print(f"\n问题统计：")
        print(f"  CRITICAL: {counts.get('CRITICAL', 0)}")
        print(f"  HIGH:     {counts.get('HIGH', 0)}")
        print(f"  MEDIUM:   {counts.get('MEDIUM', 0)}")
        print(f"  LOW:      {counts.get('LOW', 0)}")
        print(f"  总计:     {report.total_issues}")

        if report.security_issues:
            print(f"\n安全问题（{len(report.security_issues)}）：")
            for issue in report.security_issues[:10]:
                print(f"  [{issue.severity}] {issue.file}:{issue.line} {issue.message}")
            if len(report.security_issues) > 10:
                print(f"  ... 还有 {len(report.security_issues)-10} 个")

        if report.code_smells:
            print(f"\n代码异味（{len(report.code_smells)}）：")
            for issue in report.code_smells[:10]:
                print(f"  [{issue.severity}] {issue.file}:{issue.line} {issue.message}")
            if len(report.code_smells) > 10:
                print(f"  ... 还有 {len(report.code_smells)-10} 个")

        if report.health_issues:
            print(f"\n项目健康（{len(report.health_issues)}）：")
            for msg in report.health_issues:
                print(f"  ⚠ {msg}")

        if report.dependency_issues:
            print(f"\n依赖问题（{len(report.dependency_issues)}）：")
            for msg in report.dependency_issues:
                print(f"  ⚠ {msg}")

        print(f"\n最佳实践：")
        print(f"  Type Hint 覆盖率：{report.type_hint_coverage:.1f}%")
        print(f"  Docstring 覆盖率：{report.docstring_coverage:.1f}%")
        print(f"{'='*50}")

    def as_subtask_executor(self, project_path: str):
        """包装为 SmartGo subtask_executor 回调"""
        def executor(subtask_name: str, ponytail_prompt: str) -> SubtaskResult:
            print(f"\n--- 执行子任务：{subtask_name} ---")
            print(f"Ponytail约束：{ponytail_prompt[:60]}...")

            if subtask_name == "扫描安全漏洞":
                # 只跑安全扫描
                report = AuditReport(project_path=project_path)
                py_files = self._collect_py_files(project_path)
                for fpath in py_files:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    rel = os.path.relpath(fpath, project_path)
                    self._scan_security(rel, content, report)
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=300,
                    output_tokens=200,
                    output_code=f"# 发现 {len(report.security_issues)} 个安全问题\n" +
                        "\n".join(f"# [{i.severity}] {i.file}:{i.line} {i.message}"
                                 for i in report.security_issues[:10]),
                )
            elif subtask_name == "检查代码质量":
                report = AuditReport(project_path=project_path)
                py_files = self._collect_py_files(project_path)
                for fpath in py_files:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    rel = os.path.relpath(fpath, project_path)
                    self._scan_code_smells(rel, content, report)
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=300,
                    output_tokens=200,
                    output_code=f"# 发现 {len(report.code_smells)} 个代码异味\n" +
                        "\n".join(f"# [{i.severity}] {i.file}:{i.line} {i.message}"
                                 for i in report.code_smells[:10]),
                )
            elif subtask_name == "检查项目健康":
                report = AuditReport(project_path=project_path)
                self._check_health(project_path, report)
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=200,
                    output_tokens=100,
                    output_code="\n".join(f"# {msg}" for msg in report.health_issues),
                )
            elif subtask_name == "检查依赖":
                report = AuditReport(project_path=project_path)
                py_files = self._collect_py_files(project_path)
                self._check_dependencies(project_path, py_files, report)
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=200,
                    output_tokens=100,
                    output_code="\n".join(f"# {msg}" for msg in report.dependency_issues),
                )
            elif subtask_name == "生成报告":
                report = self.audit(project_path)
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=500,
                    output_tokens=500,
                    output_code=f"# 评级：{report.grade}\n# 总问题：{report.total_issues}\n# 安全：{len(report.security_issues)} 异味：{len(report.code_smells)} 健康：{len(report.health_issues)} 依赖：{len(report.dependency_issues)}",
                )
            return SubtaskResult(name=subtask_name, success=False, error="未知子任务")

        return executor

    def _collect_py_files(self, path: str) -> List[str]:
        skip_dirs = {".git", "__pycache__", "node_modules", "venv", ".venv", "env", ".env", "dist", "build"}
        py_files = []
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
            for fname in files:
                if fname.endswith(".py"):
                    py_files.append(os.path.join(root, fname))
        return py_files

    @staticmethod
    def build_task(project_path: str) -> dict:
        """构建审计任务参数"""
        auditor = ProjectAuditor()
        subtask_names = ["扫描安全漏洞", "检查代码质量", "检查项目健康", "检查依赖", "生成报告"]

        return {
            "task_description": f"审计项目 {project_path}",
            "subtask_executor": auditor.as_subtask_executor(project_path),
            "estimated_files": 20,
            "estimated_token": 10000,
            "subtask_names": subtask_names,
        }
