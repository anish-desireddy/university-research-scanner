"""Invoke and monitor a Scrapy crawl job."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from app import config as app_config
from app.utils import read_json

logger = logging.getLogger("urd.crawler")

ProgressCallback = Callable[[Dict[str, Any]], None]


class CrawlError(RuntimeError):
    pass


def _read_last_progress(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            last = None
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    continue
            return last
    except OSError:
        return None


def run_crawl(
    scan_id: str,
    start_url: str,
    options: Dict[str, Any],
    output_dir: Path,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """Run one crawl in a child process and return the parsed crawl output."""
    project_root = app_config.BASE_DIR
    log_dir = output_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    job_path = output_dir / "crawl_job.json"
    output_path = output_dir / "crawl_data.json"
    progress_path = output_dir / "crawl_progress.jsonl"
    log_path = log_dir / "crawl.log"
    for path in (progress_path, log_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    job = {
        "scan_id": scan_id,
        "start_url": start_url,
        "config": options,
        "output_path": str(output_path),
        "progress_path": str(progress_path),
        "log_path": str(log_path),
    }
    job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    command = [sys.executable, "-m", "app.crawler.run_spider", "--job", str(job_path)]
    logger.info("Launching crawler: %s", " ".join(command))
    logger.info("Crawler cwd=%s", project_root)

    max_runtime = int(options.get("max_runtime_seconds", 1200)) + 60
    started = time.time()
    last_progress_emit = 0.0
    last_progress: Optional[Dict[str, Any]] = None
    with log_path.open("ab") as log_handle:
        process = subprocess.Popen(
            command,
            cwd=str(project_root),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        try:
            while process.poll() is None:
                if time.time() - started > max_runtime:
                    process.kill()
                    raise CrawlError(
                        f"Crawl exceeded the {max_runtime}s runtime limit and was stopped."
                    )
                progress = _read_last_progress(progress_path)
                if progress and progress != last_progress:
                    last_progress = progress
                    if progress_callback:
                        progress_callback(progress)
                    last_progress_emit = time.time()
                time.sleep(0.5)
        except KeyboardInterrupt:
            process.kill()
            raise
        finally:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    if process.returncode != 0:
        tail = ""
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                tail = "".join(handle.readlines()[-30:])
        except OSError:
            pass
        raise CrawlError(
            f"The crawler exited with code {process.returncode}. "
            f"See {log_path}.\n{tail.strip()}"
        )

    data = read_json(output_path)
    if not isinstance(data, dict):
        raise CrawlError(
            "The crawler finished without producing crawl_data.json. "
            f"Check {log_path} for details."
        )
    if data.get("fatal_error") and not data.get("professors"):
        raise CrawlError(f"Unable to access the submitted website: {data['fatal_error']}")
    if data.get("js_candidates") and options.get("use_playwright"):
        try:
            from app.crawler.playwright_fetch import enrich_crawl_data
            from app.utils import atomic_write_json

            enrich_crawl_data(data, options, progress_callback)
            atomic_write_json(output_path, data)
        except Exception:
            logger.exception("Optional Playwright enrichment failed; crawl data preserved")
            data.setdefault("warnings", []).append(
                "Optional JavaScript rendering failed; server-rendered crawl data was preserved."
            )
    logger.info(
        "Crawler returned %s pages and %s professors",
        data.get("stats", {}).get("pages_visited"),
        len(data.get("professors") or []),
    )
    return data
