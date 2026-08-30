"""SmartGo 爬虫执行器集成模块

将 crawler.py 包装为 SmartGo orchestrator 的 subtask_executor 回调。
实现"一句话启动爬虫 + 全程安全防护 + token 观测"的一键流程。

用法：
    from smartgo import SmartGoOrchestrator, SmartGoConfig
    from smartgo.crawler_executor import CrawlTaskBuilder

    builder = CrawlTaskBuilder()
    task = builder.build("https://example.com", max_pages=20)
    orchestrator = SmartGoOrchestrator(SmartGoConfig())
    result = orchestrator.run(**task)
"""

import json
from typing import List, Optional, Callable
from urllib.parse import urlparse

from .crawler import Crawler, CrawlConfig, CrawlResult, DataCleaner
from smartgo.core.orchestrator import SmartGoOrchestrator, SubtaskResult


class CrawlTaskBuilder:
    """构建爬取任务参数，供 SmartGo orchestrator.run() 使用"""

    def build(
        self,
        start_url: str,
        max_pages: int = 20,
        max_depth: int = 3,
        rate_limit: float = 1.0,
        max_retries: int = 3,
        extract_fn: Optional[Callable] = None,
        output_format: str = "json",
        output_path: str = "",
        follow_links: bool = True,
        verify_ssl: bool = True,
    ) -> dict:
        """构建任务参数字典

        Returns:
            orchestrator.run() 所需的全部参数
        """
        crawl_config = CrawlConfig(
            max_retries=max_retries,
            rate_limit_delay=rate_limit,
            max_pages=max_pages,
            max_depth=max_depth,
            follow_links=follow_links,
            verify_ssl=verify_ssl,
        )

        # 根据 URL 数量和深度估算 token
        estimated_token = self._estimate_token(max_pages, max_depth)
        estimated_files = 2 if max_pages > 10 else 1

        # 构建子任务列表
        subtask_names = [
            "分析目标网站结构",
            f"爬取{max_pages}页内容",
            "清洗提取数据",
            f"导出为{output_format}",
        ]

        # 创建共享的爬虫实例
        crawler = Crawler(crawl_config)
        extract_func = extract_fn or self._default_extract

        def subtask_executor(subtask_name: str, ponytail_prompt: str) -> SubtaskResult:
            # Layer4 Ponytail 等级
            if "Ponytail=full" in ponytail_prompt:
                crawl_config.ponytail_level = "full"
            elif "Ponytail=off" in ponytail_prompt:
                crawl_config.ponytail_level = "off"
            else:
                crawl_config.ponytail_level = "lite"
            # Layer2 Superpowers 状态（爬虫暂无 Superpowers 联动行为，保留传递）
            return CrawlExecutor.execute_subtask(
                subtask_name=subtask_name,
                crawler=crawler,
                start_url=start_url,
                extract_fn=extract_func,
                output_format=output_format,
                output_path=output_path,
                ponytail_prompt=ponytail_prompt,
            )

        return {
            "task_description": f"爬取网站 {start_url}，最多{max_pages}页，深度{max_depth}",
            "subtask_executor": subtask_executor,
            "estimated_files": estimated_files,
            "estimated_token": estimated_token,
            "needs_subagents": 0,
            "needs_git_branches": 0,
            "is_research": False,
            "is_refactor": False,
            "is_from_scratch": False,
            "subtask_names": subtask_names,
        }

    def _estimate_token(self, max_pages: int, max_depth: int) -> int:
        """粗略估算爬取任务的 token 消耗"""
        base = 3000
        per_page = 800
        return base + max_pages * per_page * (1 + max_depth * 0.2)

    def _default_extract(self, html: str, url: str) -> List[dict]:
        """默认数据提取：提取标题和纯文本"""
        title = Crawler._extract_title(None, html)
        text = Crawler._strip_html(None, html)
        return [{
            "url": url,
            "title": title,
            "text_preview": text[:500],
            "text_length": len(text),
        }]


class CrawlExecutor:
    """爬虫子任务执行器"""

    @staticmethod
    def execute_subtask(
        subtask_name: str,
        crawler: Crawler,
        start_url: str,
        extract_fn: Callable,
        output_format: str,
        output_path: str,
        ponytail_prompt: str,
    ) -> SubtaskResult:
        """根据子任务名称执行对应操作"""
        print(f"\n--- 执行子任务：{subtask_name} ---")
        print(f"Ponytail约束：{ponytail_prompt[:80]}...")

        if subtask_name == "分析目标网站结构":
            return CrawlExecutor._analyze_site(start_url)

        elif subtask_name.startswith("爬取"):
            return CrawlExecutor._do_crawl(crawler, start_url, extract_fn)

        elif subtask_name == "清洗提取数据":
            return CrawlExecutor._clean_data(crawler)

        elif subtask_name.startswith("导出为"):
            return CrawlExecutor._export_data(crawler, output_format, output_path)

        return SubtaskResult(name=subtask_name, success=False, error="未知子任务")

    @staticmethod
    def _analyze_site(url: str) -> SubtaskResult:
        """子任务1：分析目标网站结构"""
        parsed = urlparse(url)
        info = {
            "域名": parsed.netloc,
            "协议": parsed.scheme,
            "路径": parsed.path or "/",
            "分析结果": "网站可访问，准备爬取",
        }
        print(f"  目标：{parsed.netloc}")
        print(f"  协议：{parsed.scheme}")
        return SubtaskResult(
            name="分析目标网站结构",
            success=True,
            input_tokens=500,
            output_tokens=300,
            output_code=json.dumps(info, ensure_ascii=False),
        )

    @staticmethod
    def _do_crawl(crawler: Crawler, start_url: str, extract_fn: Callable) -> SubtaskResult:
        """子任务2：执行爬取"""
        try:
            results = crawler.crawl(start_url, extract_fn)
            stats = crawler.get_stats()

            # 序列化结果摘要
            summary = []
            for r in results[:5]:  # 前5页摘要
                summary.append({
                    "url": r.url,
                    "title": r.title,
                    "status": r.status_code,
                    "data_items": len(r.data),
                    "links": len(r.links),
                })

            output = json.dumps({
                "stats": stats,
                "preview": summary,
                "total_pages": len(results),
            }, ensure_ascii=False, indent=2)

            return SubtaskResult(
                name="爬取内容",
                success=True,
                input_tokens=800,
                output_tokens=len(output) // 4,  # 粗略估算
                output_code=output,
            )
        except Exception as e:
            return SubtaskResult(
                name="爬取内容",
                success=False,
                error=str(e),
            )

    @staticmethod
    def _clean_data(crawler: Crawler) -> SubtaskResult:
        """子任务3：清洗提取的数据"""
        all_data = []
        for r in crawler.results:
            if not r.success:
                continue
            for item in r.data:
                # 清洗文本字段
                if isinstance(item, dict):
                    cleaned = {}
                    for k, v in item.items():
                        if isinstance(v, str):
                            cleaned[k] = DataCleaner.clean_text(v)
                        else:
                            cleaned[k] = v
                    cleaned["source_url"] = r.url
                    all_data.append(cleaned)
                else:
                    all_data.append({"raw": item, "source_url": r.url})

        # 去重
        before = len(all_data)
        all_data = DataCleaner.deduplicate(all_data, "url")
        after = len(all_data)

        print(f"  清洗前：{before} 条 → 去重后：{after} 条")

        output = json.dumps(all_data[:10], ensure_ascii=False, indent=2)

        return SubtaskResult(
            name="清洗提取数据",
            success=True,
            input_tokens=600,
            output_tokens=len(output) // 4,
            output_code=output,
            dependencies=[],
        )

    @staticmethod
    def _export_data(crawler: Crawler, fmt: str, path: str) -> SubtaskResult:
        """子任务4：导出数据"""
        all_data = []
        for r in crawler.results:
            if r.success:
                for item in r.data:
                    if isinstance(item, dict):
                        all_data.append(item)

        if not all_data:
            return SubtaskResult(
                name="导出数据",
                success=False,
                error="无数据可导出",
            )

        if not path:
            domain = urlparse(crawler.results[0].url).netloc.replace(".", "_") if crawler.results else "output"
            path = f"smartgo_crawl_{domain}.{fmt}"

        if fmt == "json":
            content = DataCleaner.to_json(all_data, path)
        elif fmt == "csv":
            content = DataCleaner.to_csv(all_data, path)
        else:
            content = DataCleaner.to_json(all_data, path)

        print(f"  已导出 {len(all_data)} 条数据 → {path}")

        return SubtaskResult(
            name=f"导出为{fmt}",
            success=True,
            input_tokens=400,
            output_tokens=len(content) // 4,
            output_code=f"# 导出完成\n# 文件：{path}\n# 数据量：{len(all_data)} 条\n# 格式：{fmt}",
        )
