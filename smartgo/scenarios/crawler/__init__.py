"""爬虫场景"""
from smartgo.scenarios.crawler.crawler import Crawler, CrawlConfig, CrawlResult, DataCleaner
from smartgo.scenarios.crawler.executor import CrawlTaskBuilder, CrawlExecutor

__all__ = ["Crawler", "CrawlConfig", "CrawlResult", "DataCleaner", "CrawlTaskBuilder", "CrawlExecutor"]
