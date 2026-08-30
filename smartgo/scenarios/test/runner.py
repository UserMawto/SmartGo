"""SmartGo 内置测试执行器

适用场景：normal_feature — 写功能后跑测试、CI 流程、测试覆盖率检查。
能力：发现测试 → 执行 → 解析结果 → 报告通过/失败/覆盖率。
与 SmartGo 安全防护层打通：测试卡住超时自动终止。
"""

import os
import re
import subprocess
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from smartgo.core.orchestrator import SubtaskResult


@dataclass
class TestResult:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration: float = 0.0
    coverage: Optional[float] = None
    failures_detail: List[dict] = field(default_factory=list)
    raw_output: str = ""


class TestRunner:
    """测试执行器

    Layer4 Ponytail（输出量）：
      full  — 最小输出，只报通过/失败总数
      lite  — 标准输出 + 失败详情
      off   — 完整输出 + 原始日志

    Layer2 Superpowers（工程流程，独立开关）：
      superpowers_enabled=True — 覆盖率分析

    用法：
        from smartgo.scenarios.test.runner import TestRunner
        runner = TestRunner(ponytail_level="lite", superpowers_enabled=False)
        result = runner.run_pytest("tests/")
    """

    def __init__(self, timeout: int = 60, coverage: bool = False,
                 ponytail_level: str = "lite", superpowers_enabled: bool = False):
        self.timeout = timeout
        self.coverage = coverage
        self.ponytail_level = ponytail_level
        self.superpowers_enabled = superpowers_enabled

    def run_pytest(self, test_path: str = "tests/") -> TestResult:
        """执行 pytest 测试"""
        if self.ponytail_level == "full":
            cmd = ["python3", "-m", "pytest", test_path, "--tb=line"]
        else:
            cmd = ["python3", "-m", "pytest", test_path, "-v", "--tb=short"]
            # Layer2 Superpowers：覆盖率分析
            if self.superpowers_enabled or self.coverage:
                cmd.extend(["--cov", "--cov-report=term-missing"])
        return self._execute(cmd, "pytest")

    def run_unittest(self, test_path: str = "tests/") -> TestResult:
        """执行 unittest 测试"""
        if self.ponytail_level == "full":
            cmd = ["python3", "-m", "unittest", "discover", "-s", test_path]
        else:
            cmd = ["python3", "-m", "unittest", "discover", "-s", test_path, "-v"]
        return self._execute(cmd, "unittest")

    def run_custom(self, command: str) -> TestResult:
        """执行自定义测试命令"""
        return self._execute(command.split(), "custom")

    def _execute(self, cmd, framework: str) -> TestResult:
        """执行测试命令并解析结果"""
        result = TestResult()
        print(f"[SmartGo 测试] 执行：{' '.join(cmd) if isinstance(cmd, list) else cmd}")

        try:
            proc = subprocess.run(
                cmd if isinstance(cmd, list) else cmd,
                shell=isinstance(cmd, str),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            output = proc.stdout + proc.stderr
            result.raw_output = output

            if framework == "pytest":
                result = self._parse_pytest(output, proc.returncode)
            elif framework == "unittest":
                result = self._parse_unittest(output, proc.returncode)
            else:
                result = self._parse_generic(output, proc.returncode)

        except subprocess.TimeoutExpired:
            result.raw_output = f"测试超时（{self.timeout}s），已终止"
            result.errors = 1
        except FileNotFoundError:
            result.raw_output = f"测试工具未安装：{cmd[0] if isinstance(cmd, list) else cmd}"
            result.errors = 1
        except Exception as e:
            result.raw_output = f"测试执行异常：{e}"
            result.errors = 1

        self._print_summary(result)
        return result

    def _parse_pytest(self, output: str, returncode: int) -> TestResult:
        """解析 pytest 输出"""
        result = TestResult(raw_output=output)

        # 匹配 "X passed, Y failed, Z error" 格式
        summary_match = re.search(
            r"(\d+)\s+passed(?:.*?(\d+)\s+failed)?(?:.*?(\d+)\s+error)?(?:.*?(\d+)\s+skipped)?",
            output,
        )
        if summary_match:
            result.passed = int(summary_match.group(1) or 0)
            result.failed = int(summary_match.group(2) or 0)
            result.errors = int(summary_match.group(3) or 0)
            result.skipped = int(summary_match.group(4) or 0)
            result.total = result.passed + result.failed + result.errors + result.skipped

        # 匹配覆盖率
        cov_match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
        if cov_match:
            result.coverage = float(cov_match.group(1))

        # 提取失败详情
        for line in output.split("\n"):
            if "FAILED" in line:
                result.failures_detail.append({
                    "test": line.strip(),
                    "framework": "pytest",
                })

        return result

    def _parse_unittest(self, output: str, returncode: int) -> TestResult:
        """解析 unittest 输出"""
        result = TestResult(raw_output=output)

        # "OK" or "FAILED (failures=X, errors=Y)"
        ok_match = re.search(r"Ran\s+(\d+)\s+tests", output)
        if ok_match:
            result.total = int(ok_match.group(1))

        if "OK" in output and returncode == 0:
            result.passed = result.total
        else:
            fail_match = re.search(r"failures=(\d+)", output)
            error_match = re.search(r"errors=(\d+)", output)
            result.failed = int(fail_match.group(1)) if fail_match else 0
            result.errors = int(error_match.group(1)) if error_match else 0
            result.passed = result.total - result.failed - result.errors

        return result

    def _parse_generic(self, output: str, returncode: int) -> TestResult:
        """通用解析"""
        return TestResult(
            total=1,
            passed=1 if returncode == 0 else 0,
            failed=0 if returncode == 0 else 1,
            raw_output=output,
        )

    def _print_summary(self, result: TestResult):
        """打印测试摘要，Ponytail 控制输出量，Superpowers 控制覆盖率"""
        status = "✅ 通过" if result.failed == 0 and result.errors == 0 else "❌ 失败"
        print(f"[SmartGo 测试] {status}")
        print(f"  总数：{result.total} | 通过：{result.passed} | 失败：{result.failed} | 错误：{result.errors} | 跳过：{result.skipped}")
        # ponytail=full：只报总数
        if self.ponytail_level == "full":
            return
        # ponytail=lite/off：输出失败详情
        if result.failures_detail:
            for f in result.failures_detail[:5]:
                print(f"  失败：{f['test']}")
        # ponytail=off：输出原始日志
        if self.ponytail_level == "off" and result.raw_output:
            lines = result.raw_output.strip().split("\n")
            if len(lines) > 20:
                print(f"  原始输出（最后20行）：")
                for line in lines[-20:]:
                    print(f"    {line}")
        # Layer2 Superpowers：覆盖率
        if self.superpowers_enabled and result.coverage is not None:
            print(f"  覆盖率：{result.coverage}%")

    def as_subtask_executor(self, test_path: str = "tests/"):
        """包装为 SmartGo subtask_executor 回调"""
        def executor(subtask_name: str, ponytail_prompt: str) -> SubtaskResult:
            print(f"\n--- 执行子任务：{subtask_name} ---")
            print(f"Ponytail约束：{ponytail_prompt[:60]}...")

            # Layer4 Ponytail 等级
            if "Ponytail=full" in ponytail_prompt:
                self.ponytail_level = "full"
            elif "Ponytail=off" in ponytail_prompt:
                self.ponytail_level = "off"
            else:
                self.ponytail_level = "lite"

            # Layer2 Superpowers 状态
            self.superpowers_enabled = "Superpowers=on" in ponytail_prompt

            if subtask_name == "发现测试":
                # 扫描测试文件
                test_files = []
                for root, _, files in os.walk(test_path):
                    for f in files:
                        if f.startswith("test_") and f.endswith(".py"):
                            test_files.append(os.path.join(root, f))
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=200,
                    output_tokens=len(str(test_files)) // 4,
                    output_code=f"# 发现 {len(test_files)} 个测试文件\n" + "\n".join(test_files[:10]),
                )
            elif subtask_name == "执行测试":
                result = self.run_pytest(test_path)
                return SubtaskResult(
                    name=subtask_name,
                    success=result.failed == 0 and result.errors == 0,
                    input_tokens=300,
                    output_tokens=len(result.raw_output) // 4,
                    output_code=result.raw_output[:500],
                    error="" if result.failed == 0 else f"{result.failed}个测试失败",
                )
            elif subtask_name == "分析覆盖率":
                runner_cov = TestRunner(timeout=self.timeout, coverage=True)
                result = runner_cov.run_pytest(test_path)
                cov_str = f"{result.coverage}%" if result.coverage else "未获取"
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=200,
                    output_tokens=100,
                    output_code=f"# 覆盖率：{cov_str}\n# 通过：{result.passed}/{result.total}",
                )
            return SubtaskResult(name=subtask_name, success=False, error="未知子任务")

        return executor

    @staticmethod
    def build_task(test_path: str = "tests/", run_coverage: bool = False) -> dict:
        """构建测试任务参数"""
        runner = TestRunner(coverage=run_coverage)
        subtask_names = ["发现测试", "执行测试"]
        if run_coverage:
            subtask_names.append("分析覆盖率")

        return {
            "task_description": f"执行测试套件 {test_path}",
            "subtask_executor": runner.as_subtask_executor(test_path),
            "estimated_files": 1,
            "estimated_token": 5000,
            "subtask_names": subtask_names,
        }
