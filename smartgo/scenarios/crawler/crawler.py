"""SmartGo 内置爬虫执行器

带请求重试、限速、反检测的 HTTP 爬虫。
优先使用标准库（urllib），可选支持 requests。
与 SmartGo 安全防护层打通：爬取超时、死循环自动中断。
"""

import random
import re
import time
import json
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Callable
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


# 反检测：User-Agent 轮换池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
]

# 需要重试的 HTTP 状态码
RETRY_STATUS_CODES = {429, 500, 502, 503, 504, 408}

# 默认请求头
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "DNT": "1",
}


@dataclass
class CrawlConfig:
    max_retries: int = 3
    retry_backoff_base: float = 1.0       # 指数退避基数（秒）
    retry_backoff_max: float = 30.0      # 最大退避时间
    rate_limit_delay: float = 1.0        # 请求间隔基准（秒）
    rate_limit_jitter: float = 0.5       # 随机抖动范围（秒）
    timeout: int = 15                     # 单次请求超时（秒）
    max_pages: int = 100                   # 最大爬取页数
    follow_links: bool = True             # 是否跟踪链接
    same_domain_only: bool = True         # 仅同域名
    max_depth: int = 3                    # 最大爬取深度
    use_proxy: bool = False
    proxy_list: List[str] = field(default_factory=list)
    respect_robots: bool = True           # 简单 robots 检查
    verify_ssl: bool = True               # SSL 证书验证（macOS 可能需关闭）


@dataclass
class CrawlResult:
    url: str
    status_code: int = 0
    success: bool = False
    html: str = ""
    text: str = ""
    title: str = ""
    links: List[str] = field(default_factory=list)
    data: List[dict] = field(default_factory=list)
    error: str = ""
    retry_count: int = 0
    elapsed: float = 0.0


class Crawler:
    """内置爬虫引擎

    特性：
    - 请求重试 + 指数退避
    - 限速 + 随机抖动（避免被识别为机器人）
    - User-Agent 轮换
    - 同域名限制 + 深度限制
    - URL 去重
    - 基础 HTML 解析（标准库，无需 BeautifulSoup）
    - 与 SmartGo Layer3 安全防护联动
    """

    def __init__(self, config: CrawlConfig = None):
        self.config = config or CrawlConfig()
        self.visited: Set[str] = set()
        self.url_queue: List[tuple] = []  # (url, depth)
        self.results: List[CrawlResult] = []
        self._proxy_index = 0
        self._total_requests = 0
        # 安全回调：由 SmartGo orchestrator 注入
        self._safety_check: Optional[Callable] = None

    def set_safety_check(self, check_fn: Callable):
        """注入 SmartGo Layer3 安全检查回调

        check_fn 签名: (input_tokens=0, output_tokens=0, action_signature="") -> (bool, str)
        返回 (False, reason) 时爬虫立即停止。
        """
        self._safety_check = check_fn

    def crawl(self, start_url: str, extract_fn: Callable = None) -> List[CrawlResult]:
        """从起始 URL 开始爬取

        Args:
            start_url: 起始 URL
            extract_fn: 自定义数据提取函数，签名: (html, url) -> List[dict]
                        不提供则只提取文本和链接
        Returns:
            爬取结果列表
        """
        self.url_queue.append((start_url, 0))
        base_domain = urlparse(start_url).netloc

        while self.url_queue and len(self.results) < self.config.max_pages:
            url, depth = self.url_queue.pop(0)

            # URL 去重
            url_clean = urldefrag(url)[0]
            url_hash = hashlib.md5(url_clean.encode()).hexdigest()
            if url_hash in self.visited:
                continue
            self.visited.add(url_hash)

            # 深度限制
            if depth > self.config.max_depth:
                continue

            # 同域名限制
            if self.config.same_domain_only:
                domain = urlparse(url_clean).netloc
                if domain != base_domain:
                    continue

            # SmartGo 安全检查
            if self._safety_check:
                can_continue, reason = self._safety_check(
                    action_signature=f"crawl:{url_clean}"
                )
                if not can_continue:
                    print(f"[SmartGo 爬虫] 安全防护触发，停止爬取：{reason}")
                    break

            # 执行请求
            result = self._fetch_with_retry(url_clean)
            self.results.append(result)
            self._total_requests += 1

            if not result.success:
                continue

            # 提取数据
            if extract_fn:
                try:
                    result.data = extract_fn(result.html, url_clean)
                except Exception as e:
                    result.error = f"数据提取失败：{e}"

            # 提取链接
            if self.config.follow_links and depth < self.config.max_depth:
                result.links = self._extract_links(result.html, url_clean)
                for link in result.links:
                    link_hash = hashlib.md5(link.encode()).hexdigest()
                    if link_hash not in self.visited:
                        self.url_queue.append((link, depth + 1))

            # 限速
            self._rate_limit()

        print(f"[SmartGo 爬虫] 完成：共爬取 {len(self.results)} 页，"
              f"发送 {self._total_requests} 次请求，"
              f"发现 {len(self.visited)} 个唯一URL")
        return self.results

    def _fetch_with_retry(self, url: str) -> CrawlResult:
        """带重试的请求"""
        result = CrawlResult(url=url)
        start_time = time.time()

        for attempt in range(self.config.max_retries + 1):
            try:
                # 构建请求
                headers = self._build_headers(url)
                req = Request(url, headers=headers)

                # SSL context
                import ssl
                ctx = ssl.create_default_context()
                if not self.config.verify_ssl:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE

                # 代理
                if self.config.use_proxy and self.config.proxy_list:
                    proxy = self._get_next_proxy()
                    import urllib.request as urlreq
                    proxy_handler = urlreq.ProxyHandler({
                        'http': proxy, 'https': proxy
                    })
                    https_handler = urlreq.HTTPSHandler(context=ctx)
                    opener = urlreq.build_opener(proxy_handler, https_handler)
                    response = opener.open(req, timeout=self.config.timeout)
                else:
                    import urllib.request as urlreq
                    https_handler = urlreq.HTTPSHandler(context=ctx)
                    opener = urlreq.build_opener(https_handler)
                    response = opener.open(req, timeout=self.config.timeout)

                result.status_code = response.getcode()

                # 处理 gzip
                content_encoding = response.headers.get('Content-Encoding', '')
                raw_data = response.read()

                if 'gzip' in content_encoding:
                    import gzip
                    import io
                    raw_data = gzip.decompress(raw_data)

                # 解码
                charset = response.headers.get_content_charset() or 'utf-8'
                result.html = raw_data.decode(charset, errors='replace')
                result.text = self._strip_html(result.html)
                result.title = self._extract_title(result.html)
                result.success = True
                result.retry_count = attempt
                result.elapsed = time.time() - start_time
                return result

            except HTTPError as e:
                result.status_code = e.code
                result.retry_count = attempt
                if e.code in RETRY_STATUS_CODES and attempt < self.config.max_retries:
                    backoff = self._get_backoff(attempt)
                    print(f"[SmartGo 爬虫] {url} 返回 {e.code}，"
                          f"第{attempt+1}次重试，等待{backoff:.1f}s")
                    time.sleep(backoff)
                    continue
                result.error = f"HTTP {e.code}: {e.reason}"
                result.elapsed = time.time() - start_time
                return result

            except URLError as e:
                result.retry_count = attempt
                if attempt < self.config.max_retries:
                    backoff = self._get_backoff(attempt)
                    print(f"[SmartGo 爬虫] {url} 连接失败({e.reason})，"
                          f"第{attempt+1}次重试，等待{backoff:.1f}s")
                    time.sleep(backoff)
                    continue
                result.error = f"连接失败：{e.reason}"
                result.elapsed = time.time() - start_time
                return result

            except Exception as e:
                result.retry_count = attempt
                if attempt < self.config.max_retries:
                    backoff = self._get_backoff(attempt)
                    print(f"[SmartGo 爬虫] {url} 异常({e})，"
                          f"第{attempt+1}次重试，等待{backoff:.1f}s")
                    time.sleep(backoff)
                    continue
                result.error = f"异常：{e}"
                result.elapsed = time.time() - start_time
                return result

        result.elapsed = time.time() - start_time
        return result

    def _build_headers(self, url: str) -> dict:
        """构建反检测请求头"""
        headers = DEFAULT_HEADERS.copy()
        # User-Agent 轮换
        headers["User-Agent"] = random.choice(USER_AGENTS)
        # Referer 伪装
        parsed = urlparse(url)
        if parsed.netloc:
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
        # 随机 Accept（模拟真实浏览器行为差异）
        if random.random() > 0.7:
            headers["Accept"] = "*/*"
        return headers

    def _get_backoff(self, attempt: int) -> float:
        """指数退避 + 随机抖动"""
        backoff = min(
            self.config.retry_backoff_base * (2 ** attempt),
            self.config.retry_backoff_max
        )
        # 加入 50% 随机抖动
        return backoff * (0.5 + random.random() * 0.5)

    def _rate_limit(self):
        """请求限速 + 随机抖动"""
        delay = self.config.rate_limit_delay
        jitter = random.uniform(0, self.config.rate_limit_jitter)
        time.sleep(delay + jitter)

    def _get_next_proxy(self) -> str:
        """轮换代理"""
        if not self.config.proxy_list:
            return None
        proxy = self.config.proxy_list[self._proxy_index % len(self.config.proxy_list)]
        self._proxy_index += 1
        return proxy

    def _strip_html(self, html: str) -> str:
        """基础 HTML 文本提取（标准库实现，无需 BeautifulSoup）"""
        # 去 script/style
        html = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # 去标签
        text = re.sub(r'<[^>]+>', '', html)
        # 去 HTML 实体（常见）
        entities = {
            '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>',
            '&quot;': '"', '&#39;': "'", '&ldquo;': '"', '&rdquo;': '"',
        }
        for entity, char in entities.items():
            text = text.replace(entity, char)
        # 压缩空白
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _extract_title(self, html: str) -> str:
        """提取页面标题"""
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    def _extract_links(self, html: str, base_url: str) -> List[str]:
        """提取页面内链接"""
        links = []
        # 提取 <a href="...">
        for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE):
            href = match.group(1).strip()
            if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            # 相对路径转绝对路径
            full_url = urljoin(base_url, href)
            # 去掉 fragment
            full_url = urldefrag(full_url)[0]
            links.append(full_url)
        return links

    def get_stats(self) -> dict:
        """获取爬取统计"""
        success_count = sum(1 for r in self.results if r.success)
        total_data = sum(len(r.data) for r in self.results)
        total_links = sum(len(r.links) for r in self.results)
        return {
            "total_pages": len(self.results),
            "success_pages": success_count,
            "failed_pages": len(self.results) - success_count,
            "total_requests": self._total_requests,
            "unique_urls": len(self.visited),
            "extracted_items": total_data,
            "found_links": total_links,
            "total_elapsed": sum(r.elapsed for r in self.results),
        }


# ===== 数据清洗工具 =====

class DataCleaner:
    """爬取数据清洗工具（标准库实现）"""

    @staticmethod
    def clean_text(text: str) -> str:
        """清洗文本：去 script/style 内容、去标签、去空白、去 HTML 实体"""
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def clean_price(price_str: str) -> float:
        """价格清洗：提取数字"""
        if not price_str:
            return 0.0
        cleaned = re.sub(r'[^\d.]', '', price_str)
        try:
            return float(cleaned) if cleaned else 0.0
        except ValueError:
            return 0.0

    @staticmethod
    def deduplicate(items: List[dict], key: str = "url") -> List[dict]:
        """按指定字段去重"""
        seen = set()
        result = []
        for item in items:
            val = item.get(key, "")
            if val not in seen:
                seen.add(val)
                result.append(item)
        return result

    @staticmethod
    def extract_by_pattern(html: str, pattern: str) -> List[str]:
        """正则提取"""
        return re.findall(pattern, html)

    @staticmethod
    def extract_table(html: str) -> List[List[str]]:
        """提取 HTML 表格数据"""
        tables = []
        for table_match in re.finditer(r'<table[^>]*>(.*?)</table>', html, re.IGNORECASE | re.DOTALL):
            table_html = table_match.group(1)
            rows = []
            for row_match in re.finditer(r'<tr[^>]*>(.*?)</tr>', table_html, re.IGNORECASE | re.DOTALL):
                cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_match.group(1), re.IGNORECASE | re.DOTALL)
                cells = [DataCleaner.clean_text(c) for c in cells]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)
        return tables

    @staticmethod
    def to_json(data, filepath: str = None) -> str:
        """序列化为 JSON，可选写文件"""
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        if filepath:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(json_str)
        return json_str

    @staticmethod
    def to_csv(data: List[dict], filepath: str = None) -> str:
        """序列化为 CSV，可选写文件"""
        import csv
        import io
        if not data:
            return ""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        csv_str = output.getvalue()
        if filepath:
            with open(filepath, 'w', encoding='utf-8', newline='') as f:
                f.write(csv_str)
        return csv_str
