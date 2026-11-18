"""Run a single crawl job with Scrapy.

Scrapy's Twisted reactor can only be started once per process, so each scan
invokes this module in a subprocess. The crawler remains programmatic Python;
no shell parsing or manual crawler operation is required.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scrapy.crawler import CrawlerProcess

from app.crawler.spider import UniversityCrawlerSpider


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True, help="Path to the crawl job JSON")
    args = parser.parse_args()
    import json

    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    config = job["config"]
    max_pages = int(config["max_pages"])
    delay = float(config["request_delay"])
    concurrency = int(config.get("concurrent_requests", 4))

    settings = {
        "ROBOTSTXT_OBEY": True,
        "USER_AGENT": config.get("user_agent"),
        "DOWNLOAD_DELAY": delay,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "DOWNLOAD_TIMEOUT": int(config.get("download_timeout", 25)),
        "CONCURRENT_REQUESTS": max(1, concurrency),
        "CONCURRENT_REQUESTS_PER_DOMAIN": max(1, min(4, concurrency)),
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": delay,
        "AUTOTHROTTLE_MAX_DELAY": max(5.0, delay * 3),
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.5,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 1,
        "COOKIES_ENABLED": False,
        "TELNETCONSOLE_ENABLED": False,
        "LOG_LEVEL": "INFO",
        "CLOSESPIDER_PAGECOUNT": max_pages + 5,
        "CLOSESPIDER_TIMEOUT": int(config.get("max_runtime_seconds", 1200)),
        "REDIRECT_MAX_TIMES": 8,
        "DEPTH_LIMIT": 0,  # The spider enforces its own relevant-link depth.
    }
    process = CrawlerProcess(settings=settings)
    process.crawl(UniversityCrawlerSpider, job_path=args.job)
    process.start()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logging.getLogger("urd.crawler").exception("Crawler process failed")
        raise
