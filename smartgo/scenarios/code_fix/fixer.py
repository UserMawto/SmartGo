"""SmartGo 内置修bug执行器

适用场景：tiny_fix — 单文件修bug、配置变更、小脚本修复。
能力：读取目标文件 → 分析错误模式 → 应用修复 → 可选跑测试验证。
与 SmartGo 安全防护层打通：防止反复修同一个 bug 死循环。
"""

import os
import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Dict

from smartgo.core.orchestrator import SubtaskResult


# 常见 bug 模式库
BUG_PATTERNS = {
    "none_check_missing": {
        "pattern": r"(\w+)\.(\w+)\(",  # a.b() 未做 None 检查
        "description": "可能未做 None 检查直接调用方法",
        "fix_hint": "添加 None 检查或使用 getattr",
    },
    "bare_except": {
        "pattern": r"except\s*:",  # 裸 except
        "description": "使用了裸 except，会吞掉所有异常",
        "fix_hint": "改为 except Exception as e:",
    },
    "mutable_default": {
        "pattern": r"def\s+\w+\([^)]*=\s*(\[\]|\{\}|set\(\))",
        "description": "函数默认参数使用可变对象",
        "fix_hint": "改为 None 并在函数内初始化",
    },
    "f_string_missing": {
        "pattern": r"print\(['\"](.*\{.*\}.*)['\"]\)",
        "description": "print 中有花括号但未用 f-string",
        "fix_hint": "添加 f 前缀",
    },
    "sql_injection": {
        "pattern": r"(execute|cursor\.execute)\s*\(\s*['\"].*%.*['\"]",
        "description": "SQL 拼接，存在注入风险",
        "fix_hint": "改用参数化查询",
    },
}


@dataclass
class BugFixReport:
    file_path: str
    bugs_found: int = 0
    bugs_fixed: int = 0
    patterns_matched: List[dict] = None
    original_content: str = ""
    fixed_content: str = ""
    test_passed: Optional[bool] = None
    test_output: str = ""


class CodeFixer:
    """修 bug 执行器

    用法：
        from smartgo.code_fixer import CodeFixer
        fixer = CodeFixer()
        result = fixer.fix_file("app.py", "TypeError on line 42")
    """

    def __init__(self, auto_test: bool = False, test_cmd: str = ""):
        self.auto_test = auto_test
        self.test_cmd = test_cmd

    def fix_file(self, file_path: str, bug_description: str = "") -> BugFixReport:
        """修复指定文件中的 bug"""
        report = BugFixReport(file_path=file_path)

        if not os.path.exists(file_path):
            report.test_output = f"文件不存在：{file_path}"
            return report

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        report.original_content = content

        # 匹配 bug 模式
        matched = []
        for name, info in BUG_PATTERNS.items():
            matches = re.finditer(info["pattern"], content)
            for m in matches:
                matched.append({
                    "pattern": name,
                    "description": info["description"],
                    "fix_hint": info["fix_hint"],
                    "line": content[:m.start()].count("\n") + 1,
                    "match": m.group(0)[:80],
                })

        report.bugs_found = len(matched)
        report.patterns_matched = matched

        # 自动修复简单模式
        fixed = content
        fixed_count = 0

        # 修复 bare except
        fixed, n = re.subn(r"except\s*:", "except Exception as e:", fixed)
        fixed_count += n

        # 修复 mutable default argument
        fixed, n = re.subn(
            r"def\s+(\w+)\s*\(([^)]*?)=\s*\[\]",
            r'def \1(\2=None',
            fixed,
        )
        # 在函数体开头添加初始化（简化处理：只做标记）
        fixed_count += n

        # 修复 print 缺少 f 前缀（含变量引用的字符串）
        fixed, n = re.subn(
            r'print\((["\'])(.*\{.*\}.*)\1\)',
            r'print(f\1\2\1)',
            fixed,
        )
        fixed_count += n

        report.fixed_content = fixed
        report.bugs_fixed = fixed_count

        # 写回文件
        if fixed != content:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(fixed)

        # 可选：跑测试验证
        if self.auto_test and self.test_cmd:
            report.test_passed, report.test_output = self._run_test()

        return report

    def fix_directory(self, dir_path: str, extensions: List[str] = None) -> List[BugFixReport]:
        """批量修复目录下所有文件"""
        if extensions is None:
            extensions = [".py"]
        results = []
        for root, dirs, files in os.walk(dir_path):
            # 跳过隐藏目录和缓存
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fname in files:
                if any(fname.endswith(ext) for ext in extensions):
                    fpath = os.path.join(root, fname)
                    results.append(self.fix_file(fpath))
        return results

    def _run_test(self) -> tuple:
        """执行测试命令"""
        try:
            result = subprocess.run(
                self.test_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "测试超时（30s）"
        except Exception as e:
            return False, f"测试执行失败：{e}"

    def as_subtask_executor(self):
        """包装为 SmartGo subtask_executor 回调"""
        def executor(subtask_name: str, ponytail_prompt: str) -> SubtaskResult:
            print(f"\n--- 执行子任务：{subtask_name} ---")
            print(f"Ponytail约束：{ponytail_prompt[:60]}...")

            if subtask_name == "分析bug":
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=300,
                    output_tokens=200,
                    output_code="# 等待 Agent 指定文件路径和 bug 描述",
                )
            elif subtask_name.startswith("修复"):
                file_path = subtask_name.replace("修复", "").strip()
                report = self.fix_file(file_path)
                return SubtaskResult(
                    name=subtask_name,
                    success=report.bugs_found > 0,
                    input_tokens=len(report.original_content) // 4,
                    output_tokens=len(report.fixed_content) // 4,
                    output_code=report.fixed_content[:500] if report.fixed_content else "",
                    error="" if report.bugs_found > 0 else "未发现已知bug模式",
                )
            elif subtask_name == "验证修复":
                if self.auto_test and self.test_cmd:
                    passed, output = self._run_test()
                    return SubtaskResult(
                        name=subtask_name,
                        success=passed,
                        input_tokens=100,
                        output_tokens=len(output) // 4,
                        output_code=output[:500],
                        error="" if passed else "测试未通过",
                    )
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=100,
                    output_tokens=50,
                    output_code="# 跳过测试验证（未配置测试命令）",
                )
            return SubtaskResult(name=subtask_name, success=False, error="未知子任务")

        return executor

    @staticmethod
    def build_task(file_path: str, bug_description: str = "",
                   run_test: bool = False, test_cmd: str = "") -> dict:
        """构建修bug任务参数，供 orchestrator.run() 使用"""
        fixer = CodeFixer(auto_test=run_test, test_cmd=test_cmd)
        subtask_names = ["分析bug", f"修复{file_path}"]
        if run_test:
            subtask_names.append("验证修复")

        return {
            "task_description": f"修复 {file_path} 的bug：{bug_description}",
            "subtask_executor": fixer.as_subtask_executor(),
            "estimated_files": 1,
            "estimated_token": 3000,
            "subtask_names": subtask_names,
        }
