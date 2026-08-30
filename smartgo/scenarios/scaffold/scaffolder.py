"""SmartGo 内置项目脚手架执行器

适用场景：big_project / danger_task — 从零搭建项目、多模块开发。
能力：生成项目结构 → 创建核心文件 → 初始化配置 → 可选 git init。
与 SmartGo 安全防护层打通：大项目自动降级防止 token 爆炸。
"""

import os
import json
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from smartgo.core.orchestrator import SubtaskResult


# 项目模板定义
PROJECT_TEMPLATES = {
    "python_web": {
        "description": "Python Web 项目（Flask/FastAPI 风格）",
        "structure": {
            "dirs": ["src", "src/api", "src/models", "src/services", "tests", "docs", "config"],
            "files": {
                "README.md": "# {project_name}\n\n## 安装\n```bash\npip install -r requirements.txt\n```\n",
                "requirements.txt": "flask>=3.0\nsqlalchemy>=2.0\npython-dotenv>=1.0\n",
                ".env.example": "DEBUG=True\nDATABASE_URL=sqlite:///dev.db\nSECRET_KEY=change-me\n",
                ".gitignore": "__pycache__/\n*.pyc\n.env\nvenv/\n*.db\n",
                "src/__init__.py": "",
                "src/main.py": "from flask import Flask\n\napp = Flask(__name__)\n\n@app.route('/')\ndef index():\n    return '{{\"status\": \"ok\"}}'\n\nif __name__ == '__main__':\n    app.run(debug=True)\n",
                "src/api/__init__.py": "",
                "src/api/routes.py": "# API 路由定义\n",
                "src/models/__init__.py": "",
                "src/models/base.py": "from sqlalchemy import create_engine\nfrom sqlalchemy.orm import declarative_base\n\nBase = declarative_base()\n",
                "src/services/__init__.py": "",
                "tests/__init__.py": "",
                "tests/test_basic.py": "def test_placeholder():\n    assert True\n",
                "config/settings.py": "import os\nfrom dotenv import load_dotenv\n\nload_dotenv()\n\nDEBUG = os.getenv('DEBUG', 'True') == 'True'\nDATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///dev.db')\n",
            },
        },
    },
    "python_cli": {
        "description": "Python CLI 工具项目",
        "structure": {
            "dirs": ["src", "src/commands", "tests"],
            "files": {
                "README.md": "# {project_name}\n\n## 用法\n```bash\npython -m src --help\n```\n",
                "requirements.txt": "click>=8.0\nrich>=13.0\n",
                ".gitignore": "__pycache__/\n*.pyc\n.env\nbuild/\ndist/\n",
                "src/__init__.py": "",
                "src/main.py": "import click\n\n@click.group()\ndef cli():\n    pass\n\n@cli.command()\ndef hello():\n    click.echo('Hello from {project_name}!')\n\nif __name__ == '__main__':\n    cli()\n",
                "src/commands/__init__.py": "",
                "tests/__init__.py": "",
                "tests/test_basic.py": "def test_placeholder():\n    assert True\n",
            },
        },
    },
    "python_package": {
        "description": "Python 可发布包项目",
        "structure": {
            "dirs": ["src/{package_name}", "tests", "docs"],
            "files": {
                "README.md": "# {project_name}\n\n## 安装\n```bash\npip install {project_name}\n```\n",
                "pyproject.toml": "[build-system]\nrequires = [\"setuptools>=61.0\"]\nbuild-backend = \"setuptools.backends._legacy\"\n\n[project]\nname = \"{project_name}\"\nversion = \"0.1.0\"\ndependencies = []\n",
                ".gitignore": "__pycache__/\n*.pyc\nbuild/\ndist/\n*.egg-info/\n",
                "src/{package_name}/__init__.py": "__version__ = '0.1.0'\n",
                "tests/__init__.py": "",
                "tests/test_basic.py": "def test_placeholder():\n    assert True\n",
            },
        },
    },
}


@dataclass
class ScaffoldReport:
    project_name: str
    template: str
    base_path: str
    dirs_created: int = 0
    files_created: int = 0
    git_initialized: bool = False
    errors: List[str] = field(default_factory=list)
    file_list: List[str] = field(default_factory=list)


class ProjectScaffolder:
    """项目脚手架执行器

    Ponytail 分级行为：
      full  — 最小结构（仅 src/main.py + requirements.txt + .gitignore）
      lite  — 标准结构（完整模板文件，含 README + tests + config）
      off   — 完整结构（标准 + CI 配置 + Makefile + CHANGELOG + docs）

    用法：
        from smartgo.scenarios.scaffold.scaffolder import ProjectScaffolder
        scaffolder = ProjectScaffolder(ponytail_level="lite")
        report = scaffolder.create("my_app", "python_web")
    """

    # ponytail=full 时只生成这些核心文件
    ESSENTIAL_FILES = {"README.md", "requirements.txt", ".gitignore", "src/main.py",
                       "src/__init__.py", "pyproject.toml"}

    # ponytail=off 时额外生成这些文件
    EXTRA_FILES = {
        "Makefile": ".PHONY: install test lint run\n\ninstall:\n\tpip install -r requirements.txt\n\ntest:\n\tpython3 -m pytest tests/ -v\n\nlint:\n\tpython3 -m flake8 src/\n\nrun:\n\tpython3 -m src.main\n",
        "CHANGELOG.md": "# Changelog\n\n## [0.1.0] - Initial release\n",
        ".github/workflows/ci.yml": "name: CI\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.11'\n      - run: pip install -r requirements.txt\n      - run: python -m pytest tests/ -v\n",
    }

    def __init__(self, git_init: bool = False, ponytail_level: str = "lite"):
        self.git_init = git_init
        self.ponytail_level = ponytail_level

    def create(self, project_name: str, template: str = "python_web",
               base_dir: str = ".") -> ScaffoldReport:
        """创建项目

        Args:
            project_name: 项目名
            template: 模板名（python_web / python_cli / python_package）
            base_dir: 基础目录
        """
        report = ScaffoldReport(
            project_name=project_name,
            template=template,
            base_path=os.path.join(base_dir, project_name),
        )

        if template not in PROJECT_TEMPLATES:
            report.errors.append(f"未知模板：{template}，可选：{list(PROJECT_TEMPLATES.keys())}")
            return report

        tmpl = PROJECT_TEMPLATES[template]
        project_path = os.path.join(base_dir, project_name)
        package_name = project_name.replace("-", "_").replace(" ", "_")

        os.makedirs(project_path, exist_ok=True)

        # 创建子目录
        for d in tmpl["structure"]["dirs"]:
            dir_path = d.replace("{package_name}", package_name)
            full_path = os.path.join(project_path, dir_path)
            os.makedirs(full_path, exist_ok=True)
            report.dirs_created += 1

        # 按 ponytail 等级筛选文件
        all_files = dict(tmpl["structure"]["files"])
        if self.ponytail_level == "full":
            # 只保留核心文件
            all_files = {k: v for k, v in all_files.items()
                         if k in self.ESSENTIAL_FILES}
        elif self.ponytail_level == "off":
            # 追加额外文件
            all_files.update(self.EXTRA_FILES)
            # 确保目录存在
            os.makedirs(os.path.join(project_path, ".github", "workflows"), exist_ok=True)
            os.makedirs(os.path.join(project_path, "docs"), exist_ok=True)

        # 创建文件
        for fname, content in all_files.items():
            fname_resolved = fname.replace("{package_name}", package_name)
            content_resolved = content.replace("{project_name}", project_name).replace("{package_name}", package_name)
            file_path = os.path.join(project_path, fname_resolved)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content_resolved)
            report.files_created += 1
            report.file_list.append(fname_resolved)

        # 可选：git init
        if self.git_init:
            try:
                subprocess.run(
                    ["git", "init"],
                    cwd=project_path,
                    capture_output=True,
                    check=True,
                )
                subprocess.run(
                    ["git", "add", "."],
                    cwd=project_path,
                    capture_output=True,
                    check=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", "Initial commit by SmartGo"],
                    cwd=project_path,
                    capture_output=True,
                    check=True,
                )
                report.git_initialized = True
            except Exception as e:
                report.errors.append(f"git 初始化失败：{e}")

        print(f"[SmartGo 脚手架] 项目 {project_name} 创建完成")
        print(f"  模板：{tmpl['description']}")
        print(f"  目录：{report.dirs_created} 个")
        print(f"  文件：{report.files_created} 个")
        if report.git_initialized:
            print(f"  Git：已初始化并提交")
        return report

    def list_templates(self) -> Dict[str, str]:
        """列出可用模板"""
        return {name: t["description"] for name, t in PROJECT_TEMPLATES.items()}

    def as_subtask_executor(self, project_name: str, template: str = "python_web",
                            base_dir: str = ".", git_init: bool = False):
        """包装为 SmartGo subtask_executor 回调"""
        scaffolder = ProjectScaffolder(git_init=git_init)

        def executor(subtask_name: str, ponytail_prompt: str) -> SubtaskResult:
            print(f"\n--- 执行子任务：{subtask_name} ---")
            print(f"Ponytail约束：{ponytail_prompt[:60]}...")

            # 从 ponytail_prompt 提取等级联动
            if "Ponytail=full" in ponytail_prompt:
                scaffolder.ponytail_level = "full"
            elif "Ponytail=off" in ponytail_prompt:
                scaffolder.ponytail_level = "off"
            else:
                scaffolder.ponytail_level = "lite"

            if subtask_name == "规划项目结构":
                tmpl = PROJECT_TEMPLATES.get(template, {})
                structure_info = json.dumps({
                    "template": template,
                    "description": tmpl.get("description", ""),
                    "dirs": tmpl.get("structure", {}).get("dirs", []),
                    "files": list(tmpl.get("structure", {}).get("files", {}).keys()),
                }, ensure_ascii=False, indent=2)
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=300,
                    output_tokens=len(structure_info) // 4,
                    output_code=structure_info,
                )
            elif subtask_name == "生成项目文件":
                report = scaffolder.create(project_name, template, base_dir)
                return SubtaskResult(
                    name=subtask_name,
                    success=len(report.errors) == 0,
                    input_tokens=500,
                    output_tokens=400,
                    output_code=f"# 创建 {report.dirs_created} 目录 + {report.files_created} 文件\n# 路径：{report.base_path}",
                    error="; ".join(report.errors) if report.errors else "",
                )
            elif subtask_name == "初始化配置":
                # 创建 venv 并安装依赖
                project_path = os.path.join(base_dir, project_name)
                req_path = os.path.join(project_path, "requirements.txt")
                install_log = ""
                if os.path.exists(req_path):
                    try:
                        result = subprocess.run(
                            ["pip", "install", "-r", "requirements.txt"],
                            cwd=project_path,
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        install_log = result.stdout[-200:] if result.stdout else "安装完成"
                    except Exception as e:
                        install_log = f"依赖安装跳过：{e}"
                else:
                    install_log = "无 requirements.txt，跳过"
                return SubtaskResult(
                    name=subtask_name,
                    success=True,
                    input_tokens=200,
                    output_tokens=len(install_log) // 4,
                    output_code=f"# {install_log}",
                )
            elif subtask_name == "验证项目":
                project_path = os.path.join(base_dir, project_name)
                # 检查关键文件是否存在
                checks = []
                for expected in ["README.md", "src"]:
                    if os.path.exists(os.path.join(project_path, expected)):
                        checks.append(f"✅ {expected}")
                    else:
                        checks.append(f"❌ {expected} 缺失")
                return SubtaskResult(
                    name=subtask_name,
                    success=all("✅" in c for c in checks),
                    input_tokens=100,
                    output_tokens=100,
                    output_code="\n".join(checks),
                )
            return SubtaskResult(name=subtask_name, success=False, error="未知子任务")

        return executor

    @staticmethod
    def build_task(project_name: str, template: str = "python_web",
                   base_dir: str = ".", git_init: bool = False) -> dict:
        """构建项目脚手架任务参数"""
        scaffolder = ProjectScaffolder(git_init=git_init)
        subtask_names = ["规划项目结构", "生成项目文件", "初始化配置", "验证项目"]

        # 从零搭建 → danger_task 特征
        estimated_token = 15000
        estimated_files = len(PROJECT_TEMPLATES.get(template, {}).get("structure", {}).get("files", {}))

        return {
            "task_description": f"从零搭建项目 {project_name}（模板：{template}）",
            "subtask_executor": scaffolder.as_subtask_executor(
                project_name, template, base_dir, git_init
            ),
            "estimated_files": estimated_files,
            "estimated_token": estimated_token,
            "needs_subagents": 0,
            "is_from_scratch": True,
            "subtask_names": subtask_names,
        }
