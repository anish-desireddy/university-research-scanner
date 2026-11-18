"""Scan orchestration: crawl, AI analysis, JSON, and PDF."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app import __version__
from app.ai.analyzer import ProfessorAnalyzer
from app.backend.store import ScanStore
from app.config import default_scan_options
from app.crawler.runner import CrawlError, run_crawl
from app.reporting.json_report import write_json_report
from app.reporting.pdf_report import write_pdf_report
from app.utils import (
    now_iso,
    read_json,
    scan_timestamp,
    validate_start_url,
)

logger = logging.getLogger("urd.backend")

STAGE_PROGRESS = {
    "initializing": 2,
    "accessing": 6,
    "discovering": 16,
    "identifying": 30,
    "extracting": 45,
    "publications": 60,
    "ai_analysis": 66,
    "generating_json": 88,
    "generating_pdf": 94,
    "completed": 100,
    "failed": 100,
}


class ScanBusyError(RuntimeError):
    pass


class ScanNotFoundError(RuntimeError):
    pass


class ScanManager:
    def __init__(
        self,
        config: Dict[str, Any],
        store: Optional[ScanStore] = None,
        analyzer_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.config = config
        self.store = store or ScanStore(config["database"]["path"])
        self.analyzer_factory = analyzer_factory or (lambda cfg: ProfessorAnalyzer(cfg))
        self._lock = threading.Lock()
        self._active_scan: Optional[str] = None
        self._health_cache: Optional[Dict[str, Any]] = None
        self._health_cached_at = 0.0
        interrupted = self.store.mark_interrupted()
        if interrupted:
            logger.warning("Marked %s interrupted scan(s) as failed", interrupted)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_scan(self, url: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        normalized_url = validate_start_url(url)
        options = self._normalize_options(overrides or {})
        with self._lock:
            if self._active_scan:
                raise ScanBusyError(
                    "A scan is already running. Wait for it to finish before starting another."
                )
            scan_id, output_dir = self._create_output_dir()
            self._active_scan = scan_id
            record = {
                "id": scan_id,
                "url": normalized_url,
                "status": "running",
                "stage": "initializing",
                "progress": 1,
                "message": "Initializing scan",
                "config": options,
                "output_dir": str(output_dir),
            }
            self.store.create_scan(record)
        logger.info("Starting scan %s for %s", scan_id, normalized_url)
        logger.info("Output directory: %s", output_dir)
        thread = threading.Thread(
            target=self._run_scan,
            args=(scan_id, normalized_url, options, output_dir),
            name=f"scan-{scan_id}",
            daemon=True,
        )
        thread.start()
        return self.get_status(scan_id)

    def get_status(self, scan_id: str) -> Dict[str, Any]:
        record = self.store.get_scan(scan_id)
        if not record:
            raise ScanNotFoundError(f"Scan {scan_id} was not found.")
        return self._status_payload(record)

    def list_scans(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [self._status_payload(record) for record in self.store.list_scans(limit)]

    def get_results(self, scan_id: str) -> Dict[str, Any]:
        record = self.store.get_scan(scan_id)
        if not record:
            raise ScanNotFoundError(f"Scan {scan_id} was not found.")
        path = record.get("json_path")
        if not path:
            raise FileNotFoundError("This scan does not have a JSON report yet.")
        data = read_json(path)
        if not isinstance(data, dict):
            raise FileNotFoundError("The JSON report could not be read.")
        return data

    def download_path(self, scan_id: str, kind: str) -> Path:
        record = self.store.get_scan(scan_id)
        if not record:
            raise ScanNotFoundError(f"Scan {scan_id} was not found.")
        if kind == "json":
            path = record.get("json_path")
        elif kind == "pdf":
            path = record.get("pdf_path")
        else:
            raise ValueError("Download type must be 'json' or 'pdf'.")
        if not path:
            raise FileNotFoundError(f"The {kind.upper()} report is not available for this scan.")
        target = Path(path)
        if not target.exists():
            raise FileNotFoundError(f"The {kind.upper()} report file is missing.")
        return target

    def retry_ai(self, scan_id: str, force_refresh: bool = False) -> Dict[str, Any]:
        record = self.store.get_scan(scan_id)
        if not record:
            raise ScanNotFoundError(f"Scan {scan_id} was not found.")
        output_dir = Path(record["output_dir"])
        crawl_path = output_dir / "crawl_data.json"
        crawl_data = read_json(crawl_path)
        if not isinstance(crawl_data, dict):
            raise FileNotFoundError(
                "The crawl data for this scan is no longer available, so AI analysis cannot be retried."
            )
        with self._lock:
            if self._active_scan:
                raise ScanBusyError("A scan is already running.")
            self._active_scan = scan_id
        self.store.update_scan(
            scan_id,
            status="running",
            stage="ai_analysis",
            progress=STAGE_PROGRESS["ai_analysis"],
            message="Retrying AI analysis with Ollama",
            error=None,
        )
        logger.info("Retrying AI analysis for scan %s", scan_id)
        thread = threading.Thread(
            target=self._run_ai_retry,
            args=(scan_id, record, crawl_data, force_refresh),
            name=f"retry-{scan_id}",
            daemon=True,
        )
        thread.start()
        return self.get_status(scan_id)

    def health(self) -> Dict[str, Any]:
        now = time.time()
        if self._health_cache and now - self._health_cached_at < 5:
            return self._health_cache
        try:
            status = self.analyzer_factory(self.config["ollama"]).status()
        except Exception as exc:  # health must never crash the server
            logger.exception("Ollama health check failed")
            status = {
                "provider": "ollama",
                "model": self.config["ollama"]["model"],
                "available": False,
                "model_installed": False,
                "message": f"Ollama health check failed: {exc}",
                "setup_instructions": [
                    "Start Ollama with: ollama serve",
                    f"Pull the configured model: ollama pull {self.config['ollama']['model']}",
                ],
            }
        self._health_cache = status
        self._health_cached_at = now
        return status

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def _run_scan(
        self,
        scan_id: str,
        url: str,
        options: Dict[str, Any],
        output_dir: Path,
    ) -> None:
        started_at = now_iso()
        try:
            logger.info("[%s] Stage initializing", scan_id)
            self.store.update_scan(
                scan_id,
                stage="initializing",
                progress=STAGE_PROGRESS["initializing"],
                message="Initializing crawler",
                status="running",
            )
            crawl_data = run_crawl(
                scan_id,
                url,
                options,
                output_dir,
                progress_callback=lambda progress: self._apply_crawl_progress(
                    scan_id, progress
                ),
            )
            self._process_crawl_result(
                scan_id,
                crawl_data,
                options,
                output_dir,
                started_at=started_at,
                existing_record=None,
            )
        except (CrawlError, ValueError, FileNotFoundError) as exc:
            logger.exception("[%s] Scan failed", scan_id)
            self.store.update_scan(
                scan_id,
                status="failed",
                stage="failed",
                progress=100,
                message="Scan failed",
                error=str(exc),
                completed_at=now_iso(),
            )
        except Exception as exc:
            logger.exception("[%s] Unexpected scan failure", scan_id)
            self.store.update_scan(
                scan_id,
                status="failed",
                stage="failed",
                progress=100,
                message="Scan failed with an unexpected error",
                error=f"{type(exc).__name__}: {exc}",
                completed_at=now_iso(),
            )
        finally:
            with self._lock:
                if self._active_scan == scan_id:
                    self._active_scan = None

    def _run_ai_retry(
        self,
        scan_id: str,
        record: Dict[str, Any],
        crawl_data: Dict[str, Any],
        force_refresh: bool,
    ) -> None:
        try:
            options = record.get("config") or self._normalize_options({})
            self._process_crawl_result(
                scan_id,
                crawl_data,
                options,
                Path(record["output_dir"]),
                started_at=record.get("created_at") or now_iso(),
                existing_record=record,
                force_refresh=force_refresh,
            )
        except Exception as exc:
            logger.exception("[%s] AI retry failed", scan_id)
            self.store.update_scan(
                scan_id,
                status="failed",
                stage="failed",
                progress=100,
                message="AI retry failed",
                error=f"{type(exc).__name__}: {exc}",
                completed_at=now_iso(),
            )
        finally:
            with self._lock:
                if self._active_scan == scan_id:
                    self._active_scan = None

    def _process_crawl_result(
        self,
        scan_id: str,
        crawl_data: Dict[str, Any],
        options: Dict[str, Any],
        output_dir: Path,
        started_at: str,
        existing_record: Optional[Dict[str, Any]],
        force_refresh: bool = False,
    ) -> None:
        professors = crawl_data.get("professors") or []
        crawl_stats = crawl_data.get("stats") or {}
        pages = int(crawl_stats.get("pages_visited") or 0)
        publications = int(crawl_stats.get("publications_collected") or 0)
        errors_count = int(crawl_stats.get("errors") or 0)
        warnings = list(crawl_data.get("warnings") or [])
        self.store.update_scan(
            scan_id,
            stage="ai_analysis",
            progress=STAGE_PROGRESS["ai_analysis"],
            message="Crawl complete. Checking local Ollama model",
            pages=pages,
            professors_found=len(professors),
            publications_found=publications,
            warnings_count=len(warnings),
            errors_count=errors_count,
            external_domains=len(crawl_data.get("external_domains") or []),
        )

        ai_info = self._run_ai_stage(scan_id, professors, force_refresh)
        if ai_info["status"] in ("unavailable", "model_missing", "failed", "skipped", "partial"):
            message = ai_info.get("message") or f"AI analysis {ai_info['status']}"
            if message not in warnings:
                warnings.append(message)
        if ai_info.get("errors"):
            for error in ai_info["errors"]:
                crawl_data.setdefault("manual_review", []).append(
                    {
                        "url": error.get("profile_url"),
                        "reason": "ai_analysis_failed",
                        "professor": error.get("name"),
                        "detail": error.get("error"),
                    }
                )
        crawl_data["warnings"] = warnings

        analyzed = sum(
            1 for professor in professors if professor.get("opportunity", {}).get("category")
        )
        summary = self._build_summary(professors, crawl_stats, analyzed)
        result = self._build_result(
            scan_id=scan_id,
            url=(existing_record or {}).get("url") or crawl_data["scan"]["start_url"],
            crawl_data=crawl_data,
            options=options,
            ai_info=ai_info,
            summary=summary,
            started_at=started_at,
            professors=professors,
        )
        self.store.update_scan(
            scan_id,
            analyzed_count=analyzed,
            summary_json=summary,
            ai_json=ai_info,
            warnings_count=len(warnings),
        )
        logger.info(
            "[%s] AI status=%s analyzed=%s/%s",
            scan_id,
            ai_info["status"],
            analyzed,
            len(professors),
        )

        self.store.update_scan(
            scan_id,
            stage="generating_json",
            progress=STAGE_PROGRESS["generating_json"],
            message="Writing comprehensive JSON report",
        )
        json_path = output_dir / "research_results.json"
        try:
            write_json_report(result, json_path)
        except Exception as exc:
            logger.exception("[%s] JSON generation failed", scan_id)
            self.store.update_scan(
                scan_id,
                status="failed",
                stage="failed",
                progress=100,
                message="JSON report generation failed",
                error=f"JSON generation failed: {exc}",
                completed_at=now_iso(),
            )
            return
        self.store.update_scan(scan_id, json_path=str(json_path))

        self.store.update_scan(
            scan_id,
            stage="generating_pdf",
            progress=STAGE_PROGRESS["generating_pdf"],
            message="Building professional PDF report",
        )
        pdf_path = output_dir / "research_report.pdf"
        pdf_error = None
        pdf_ok = False
        try:
            write_pdf_report(result, pdf_path)
            pdf_ok = True
            self.store.update_scan(scan_id, pdf_path=str(pdf_path))
        except Exception as exc:
            logger.exception("[%s] PDF generation failed", scan_id)
            pdf_error = f"PDF generation failed: {type(exc).__name__}: {exc}"
            result["scan"]["pdf_error"] = pdf_error
            if pdf_error not in warnings:
                warnings.append(pdf_error)
                result["crawl"]["warnings"] = warnings
            try:
                write_json_report(result, json_path)
            except Exception:
                logger.exception("[%s] Could not update JSON with PDF error", scan_id)

        completed_at = now_iso()
        status = "completed" if pdf_ok else "completed_with_errors"
        message = (
            f"Scan complete: {len(professors)} professors, {analyzed} analyzed"
            if pdf_ok
            else "Scan complete, but the PDF report could not be generated. JSON is available."
        )
        self.store.update_scan(
            scan_id,
            status=status,
            stage="completed",
            progress=100,
            message=message,
            completed_at=completed_at,
            analyzed_count=analyzed,
            summary_json=summary,
            ai_json=ai_info,
            warnings_count=len(warnings),
            errors_count=errors_count,
        )
        logger.info(
            "[%s] Scan complete: status=%s json=%s pdf=%s",
            scan_id,
            status,
            json_path,
            pdf_path if pdf_ok else "not generated",
        )

    # ------------------------------------------------------------------
    # AI stage
    # ------------------------------------------------------------------

    def _run_ai_stage(
        self, scan_id: str, professors: List[Dict[str, Any]], force_refresh: bool
    ) -> Dict[str, Any]:
        ai_info: Dict[str, Any] = {
            "provider": "ollama",
            "model": self.config["ollama"]["model"],
            "status": "not_run",
            "available": False,
            "model_installed": False,
            "message": "",
            "setup_instructions": [],
            "analyses_completed": 0,
            "analyses_failed": 0,
            "errors": [],
            "started_at": now_iso(),
            "finished_at": None,
        }
        if not professors:
            ai_info["status"] = "skipped"
            ai_info["message"] = "No professors were identified, so AI analysis was not run."
            ai_info["finished_at"] = now_iso()
            return ai_info
        try:
            analyzer = self.analyzer_factory(self.config["ollama"])
            status = analyzer.status()
        except Exception as exc:
            logger.exception("[%s] Could not initialize Ollama client", scan_id)
            ai_info["status"] = "failed"
            ai_info["message"] = f"Could not initialize Ollama: {exc}"
            ai_info["finished_at"] = now_iso()
            return ai_info
        ai_info["available"] = bool(status.get("available"))
        ai_info["model_installed"] = bool(status.get("model_installed"))
        ai_info["setup_instructions"] = status.get("setup_instructions") or []
        if not status.get("available"):
            ai_info["status"] = "unavailable"
            ai_info["message"] = status.get("message") or "Ollama is not available."
            ai_info["finished_at"] = now_iso()
            logger.warning("[%s] AI unavailable: %s", scan_id, ai_info["message"])
            return ai_info
        if not status.get("model_installed"):
            ai_info["status"] = "model_missing"
            ai_info["message"] = status.get("message") or "Configured model is not installed."
            ai_info["finished_at"] = now_iso()
            logger.warning("[%s] AI model missing: %s", scan_id, ai_info["message"])
            return ai_info

        total = len(professors)
        results: Dict[str, Dict[str, Any]] = {}
        errors: List[Dict[str, Any]] = []
        max_workers = max(1, int(self.config["ollama"].get("max_concurrent_requests", 2)))
        logger.info(
            "[%s] Running Ollama analysis for %s professors (concurrency=%s)",
            scan_id,
            total,
            max_workers,
        )
        completed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(analyzer.analyze, professor, force_refresh): professor
                for professor in professors
            }
            for future in concurrent.futures.as_completed(future_map):
                professor = future_map[future]
                try:
                    results[professor["id"]] = future.result()
                except Exception as exc:
                    logger.exception(
                        "[%s] AI analysis failed for %s", scan_id, professor.get("name")
                    )
                    errors.append(
                        {
                            "professor_id": professor.get("id"),
                            "name": professor.get("name"),
                            "profile_url": professor.get("profile_url"),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                completed += 1
                self._merge_analysis(professor, results.get(professor["id"]), errors[-1] if errors and errors[-1].get("professor_id") == professor.get("id") else None)
                progress = STAGE_PROGRESS["ai_analysis"] + int(
                    18 * completed / max(1, total)
                )
                self.store.update_scan(
                    scan_id,
                    stage="ai_analysis",
                    progress=progress,
                    message=f"Analyzing with Ollama · {completed}/{total} professors",
                    analyzed_count=sum(
                        1
                        for item in professors
                        if (item.get("opportunity") or {}).get("category")
                    ),
                )

        analyzed = sum(
            1 for professor in professors if professor.get("opportunity", {}).get("category")
        )
        ai_info["analyses_completed"] = analyzed
        ai_info["analyses_failed"] = len(errors)
        ai_info["errors"] = errors
        ai_info["finished_at"] = now_iso()
        if analyzed == 0:
            ai_info["status"] = "failed"
            ai_info["message"] = (
                "Ollama was available, but no professor received a valid analysis. "
                "Crawl results were preserved; AI analysis can be retried."
            )
        elif errors or analyzed < total:
            ai_info["status"] = "partial"
            ai_info["message"] = (
                f"AI analysis completed for {analyzed} of {total} professors. "
                "Crawl results and successful analyses were preserved."
            )
        else:
            ai_info["status"] = "complete"
            ai_info["message"] = f"AI analysis completed for all {analyzed} professors."
        return ai_info

    def _merge_analysis(
        self,
        professor: Dict[str, Any],
        analysis: Optional[Dict[str, Any]],
        error: Optional[Dict[str, Any]] = None,
    ) -> None:
        research = professor.setdefault("research", {})
        opportunity = professor.setdefault("opportunity", {})
        provenance = professor.setdefault("provenance", {})
        if not analysis:
            opportunity["status"] = "failed" if error else "not_analyzed"
            professor["analysis"] = {
                "status": "failed",
                "provider": "ollama",
                "model": self.config["ollama"]["model"],
                "error": (error or {}).get("error") or "AI analysis did not run.",
            }
            return
        status = analysis.get("status")
        if analysis.get("research_summary"):
            research["summary"] = analysis["research_summary"]
            research["ai_generated"] = True
        research["ai_interests"] = analysis.get("ai_interests") or []
        research["ai_methodologies"] = analysis.get("ai_methodologies") or []
        research["ai_technologies"] = analysis.get("ai_technologies") or []
        research["ai_current_projects"] = analysis.get("ai_current_projects") or []
        research["publication_analysis"] = analysis.get("publication_analysis")
        research["publication_topics"] = analysis.get("publication_topics") or []
        opportunity["category"] = analysis.get("category")
        opportunity["category_label"] = analysis.get("category_label")
        opportunity["confidence"] = analysis.get("confidence")
        opportunity["confidence_explanation"] = analysis.get("confidence_explanation")
        opportunity["explanation"] = analysis.get("classification_explanation")
        if analysis.get("opportunity_evidence"):
            opportunity["evidence"] = analysis["opportunity_evidence"]
        opportunity["evidence_found"] = bool(opportunity.get("evidence"))
        opportunity["status"] = (
            "analyzed" if analysis.get("category") is not None else "failed"
        )
        opportunity["assessment_status"] = analysis.get("opportunity_status")
        professor["analysis"] = {
            "status": status,
            "provider": "ollama",
            "model": analysis.get("model"),
            "generated_at": analysis.get("generated_at"),
            "cached": analysis.get("cached", False),
        }
        ai_fields = sorted(
            set(provenance.get("ai_generated_fields") or [])
            | {
                "research.summary",
                "research.ai_interests",
                "research.publication_analysis",
                "opportunity.category",
                "opportunity.confidence",
                "opportunity.explanation",
            }
        )
        provenance["ai_generated_fields"] = ai_fields

    # ------------------------------------------------------------------
    # Result building
    # ------------------------------------------------------------------

    def _build_summary(
        self,
        professors: List[Dict[str, Any]],
        crawl_stats: Dict[str, Any],
        analyzed: int,
    ) -> Dict[str, Any]:
        counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for professor in professors:
            category = (professor.get("opportunity") or {}).get("category")
            if category in counts:
                counts[category] += 1
        return {
            "professors_identified": len(professors),
            "professors_analyzed": analyzed,
            "confirmed_open": counts[1],
            "actively_recruiting": counts[2],
            "potential_opportunity": counts[3],
            "no_information": counts[4],
            "not_analyzed": len(professors) - analyzed,
            "pages_visited": int(crawl_stats.get("pages_visited") or 0),
            "publications_collected": int(crawl_stats.get("publications_collected") or 0),
            "evidence_snippets": int(crawl_stats.get("evidence_snippets") or 0),
            "errors": int(crawl_stats.get("errors") or 0),
            "manual_review": int(crawl_stats.get("manual_review") or 0),
        }

    def _build_result(
        self,
        scan_id: str,
        url: str,
        crawl_data: Dict[str, Any],
        options: Dict[str, Any],
        ai_info: Dict[str, Any],
        summary: Dict[str, Any],
        started_at: str,
        professors: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        completed_at = now_iso()
        crawl_stats = dict(crawl_data.get("stats") or {})
        crawl_stats["professors_analyzed"] = summary["professors_analyzed"]
        crawl_stats["ai_analyses_failed"] = ai_info.get("analyses_failed", 0)
        return {
            "schema_version": "1.0",
            "application": {
                "name": "University Research Discovery",
                "version": __version__,
            },
            "scan": {
                "id": scan_id,
                "url": url,
                "final_url": (crawl_data.get("scan") or {}).get("final_start_url") or url,
                "created_at": started_at,
                "completed_at": completed_at,
                "status": "completed",
                "config": options,
                "university": crawl_data.get("university") or "",
                "department": crawl_data.get("department") or "",
                "summary": summary,
                "ai": ai_info,
                "stats": crawl_stats,
                "warnings": crawl_data.get("warnings") or [],
            },
            "university": crawl_data.get("university") or "",
            "department": crawl_data.get("department") or "",
            "professors": professors,
            "crawl": {
                "stats": crawl_stats,
                "pages": crawl_data.get("pages") or [],
                "errors": crawl_data.get("errors") or [],
                "manual_review": crawl_data.get("manual_review") or [],
                "external_domains": crawl_data.get("external_domains") or [],
                "warnings": crawl_data.get("warnings") or [],
                "js_candidates": crawl_data.get("js_candidates") or [],
            },
            "methodology": {
                "discovery": "Relevance-scored breadth-first crawl of university and linked academic pages.",
                "extraction": "Semantic HTML, schema.org Person data, person-card heuristics, and explicit publication sections.",
                "ai_provider": "Ollama",
                "ai_model": ai_info.get("model"),
                "opportunity_categories": {
                    "1": "Confirmed open position",
                    "2": "Actively recruiting / welcoming students",
                    "3": "Potential opportunity",
                    "4": "No opportunity information found",
                },
                "confidence_meaning": "Strength and quality of evidence, not probability of acceptance.",
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_crawl_progress(self, scan_id: str, progress: Dict[str, Any]) -> None:
        stage = progress.get("stage") or "discovering"
        if stage == "crawl_complete":
            stage = "ai_analysis"
        if stage not in STAGE_PROGRESS:
            stage = "discovering"
        pages = int(progress.get("pages") or 0)
        professors = int(progress.get("professors") or 0)
        publications = int(progress.get("publications") or 0)
        warnings = int(progress.get("warnings") or 0)
        errors = int(progress.get("errors") or 0)
        external = int(progress.get("external_domains") or 0)
        message_parts = [f"{pages}/{progress.get('max_pages', '?')} pages", f"{professors} professors"]
        if publications:
            message_parts.append(f"{publications} publications")
        if warnings:
            message_parts.append(f"{warnings} warnings")
        self.store.update_scan(
            scan_id,
            stage=stage,
            progress=STAGE_PROGRESS.get(stage, 16),
            message=" · ".join(message_parts),
            pages=pages,
            professors_found=professors,
            publications_found=publications,
            warnings_count=warnings,
            errors_count=errors,
            external_domains=external,
        )

    def _normalize_options(self, overrides: Dict[str, Any]) -> Dict[str, Any]:
        options = default_scan_options(self.config)
        numeric_rules = {
            "max_depth": (0, 6, int),
            "max_pages": (1, 500, int),
            "max_external_domains": (0, 100, int),
            "request_delay": (0.0, 5.0, float),
        }
        for key, (low, high, cast) in numeric_rules.items():
            if overrides.get(key) is None:
                continue
            try:
                value = cast(overrides[key])
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a number.")
            if value < low or value > high:
                raise ValueError(f"{key} must be between {low} and {high}.")
            options[key] = value
        return options

    def _create_output_dir(self) -> tuple[str, Path]:
        root = Path(self.config["output"]["directory"])
        root.mkdir(parents=True, exist_ok=True)
        stamp = scan_timestamp()
        candidate = root / f"scan_{stamp}"
        counter = 2
        while candidate.exists():
            candidate = root / f"scan_{stamp}_{counter}"
            counter += 1
        candidate.mkdir(parents=True, exist_ok=False)
        return candidate.name, candidate

    def _status_payload(self, record: Dict[str, Any]) -> Dict[str, Any]:
        json_path = record.get("json_path")
        pdf_path = record.get("pdf_path")
        ai = record.get("ai") or {}
        return {
            "id": record.get("id"),
            "url": record.get("url"),
            "status": record.get("status"),
            "stage": record.get("stage"),
            "progress": int(record.get("progress") or 0),
            "message": record.get("message") or "",
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "completed_at": record.get("completed_at"),
            "error": record.get("error"),
            "counters": {
                "pages": int(record.get("pages") or 0),
                "professors": int(record.get("professors_found") or 0),
                "publications": int(record.get("publications_found") or 0),
                "analyzed": int(record.get("analyzed_count") or 0),
                "warnings": int(record.get("warnings_count") or 0),
                "errors": int(record.get("errors_count") or 0),
                "external_domains": int(record.get("external_domains") or 0),
            },
            "summary": record.get("summary") or {},
            "ai": {
                "status": ai.get("status"),
                "model": ai.get("model") or self.config["ollama"]["model"],
                "message": ai.get("message"),
                "setup_instructions": ai.get("setup_instructions") or [],
                "analyses_completed": ai.get("analyses_completed"),
                "analyses_failed": ai.get("analyses_failed"),
            },
            "downloads": {
                "json": bool(json_path and Path(json_path).exists()),
                "pdf": bool(pdf_path and Path(pdf_path).exists()),
            },
        }
