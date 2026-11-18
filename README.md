# Instructions to run this project

## Features

- Broad website crawling across university and relevant external academic websites
- Professor identification and research profile collection
- Research interests and publication discovery
- AI-powered analysis using locally hosted Ollama models
- Research opportunity classification with confidence scores
- Supporting evidence and source URLs
- Downloadable JSON data and PDF reports
- Browser-based interface

## Requirements

- Python 3.9 or newer (use the version supported by the project's dependencies)
- [Ollama](https://ollama.com/)
- Google Chrome or another supported browser
- Git

## Installation

### 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd YOUR_PROJECT_FOLDER
```

### 2. Create a virtual environment

Mac/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows:

```powershell
py -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up Ollama

Install Ollama and download the model specified in the project's configuration.

Check that Ollama is running before launching the application.

```bash
ollama list
```

If the required model is not installed, download it using the model name specified by the project.

## Running the Application

From the project directory, with the virtual environment activated:

```bash
python main.py
```

The application should start its local server and open the web interface in your browser.

Paste a university website URL into the application and start a scan.

## Output

The application generates two primary files:

- **JSON:** Comprehensive structured data containing professor profiles, research information, opportunity classifications, confidence scores, evidence, and source URLs.
- **PDF:** A concise report summarizing the scan and its findings.

Both files can be downloaded through the web interface.

## Important Notes

- Ollama runs locally. Each teammate must install Ollama and the required model on their own computer.
- Opportunity classifications are based on publicly available evidence. They do not guarantee that a professor currently has an opening.
- Confidence scores reflect the strength of the available evidence, not the probability of receiving a research position.
- Results may require manual verification.
- Respect website crawling policies and robots.txt.

## Team Development

Contributions are welcome. Please create a separate Git branch for significant changes and test your changes before submitting a pull request.

## Project Status

Active development.




# University Research Discovery

A locally hosted application that crawls university websites, identifies faculty,
collects research and publication information, and uses a local Ollama model to
assess publicly available undergraduate research opportunities.

Everything is orchestrated by one command:

```bash
python main.py
```

The launcher checks dependencies and configuration, checks Ollama, starts the
FastAPI backend, waits until the server is ready, opens Google Chrome, and keeps
running until you stop it. If Chrome cannot be found, it opens the default browser
and prints the local URL.

---

## What it produces

Every successful scan creates a new, timestamped folder:

```text
outputs/
  scan_YYYY-MM-DD_HHMMSS/
    research_results.json   # comprehensive UTF-8 dataset
    research_report.pdf     # concise professional PDF for every professor
    crawl_data.json         # intermediate crawl snapshot, used for AI retries
    crawl_progress.jsonl    # live crawl progress
    crawl.log               # Scrapy crawl log
    crawl_job.json          # reproducible crawl job description
```

Previous scans are never overwritten. The filenames requested by the project
specification are always:

- `research_results.json`
- `research_report.pdf`

The PDF includes a cover page, executive summary, a directory table containing
every professor, individual professor summaries, consolidated opportunity
findings, methodology, limitations, page numbers, and clickable source links.

---

## Quick start

### 1. Install Python dependencies

```bash
python -m pip install -r requirements.txt
```

Tested with Python 3.14.6. The application code is compatible with Python 3.9+.

### 2. Install and start Ollama

macOS:

```bash
brew install ollama
ollama serve
```

Or install from <https://ollama.com/download>.

The default configured model is `llama3.2:latest` (a 3B model, about 2 GB on
disk). It is a reasonable balance for a MacBook Air M4 with 16 GB of RAM.

```bash
ollama pull llama3.2:latest
```

Verify:

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

Change the model in `config.yaml` if desired:

```yaml
ollama:
  base_url: "http://127.0.0.1:11434"
  model: "llama3.2:latest"
```

The application checks that Ollama is reachable and that the configured model is
installed. It never silently substitutes another model. If the model is missing,
the UI shows the exact `ollama pull` command. Crawl results and reports are still
produced, and AI analysis can be retried from the results page.

### 3. Launch

```bash
python main.py
```

Useful options:

```bash
python main.py --no-browser
python main.py --port 9000
python main.py --host 127.0.0.1
```

Default URL: <http://127.0.0.1:8765>

If the configured port is occupied, the launcher selects the next free port and
prints it.

### 4. Run a scan

Paste a university department, faculty directory, professor profile, laboratory,
or research-center URL and press **Run Scan**. The default settings are:

| Setting | Default |
|---|---|
| Maximum crawl depth | 3 |
| Maximum pages | 100 |
| Maximum external domains | 20 |
| Request delay | 1.0 second |
| Concurrent requests | 4 |

The website shows the ten scan stages, page/professor/publication counts, warnings,
and errors. When the scan finishes, download the JSON and PDF directly from the
results dashboard.

---

## Architecture

```text
main.py                         Single-command launcher, dependency/config checks,
                                Ollama check, server readiness, Chrome launch
config.yaml                     Crawl, Ollama, output, logging configuration

app/
  config.py                     Config loading, defaults, path resolution
  logging_setup.py              Console + rotating file logging
  utils.py                      URL validation, JSON, domains, text helpers

  crawler/
    spider.py                   Scrapy spider, relevance scheduling, professor merge,
                                progress records, crawl errors and manual review
    extraction.py               Generic HTML extraction for listings, profiles,
                                research, publications, labs, academic profiles,
                                opportunity evidence
    relevance.py                Link relevance and external-domain rules
    run_spider.py               One process-safe Scrapy run
    runner.py                   Programmatic subprocess + progress polling
    playwright_fetch.py         Optional JavaScript fallback, only for JS-suspect pages

  ai/
    client.py                   Ollama API client and model checks
    cache.py                    SQLite cache of completed analyses
    prompts.py                  Shared grounded prompt construction
    summary.py                  Research summarization module
    publications.py             Publication theme analysis module
    opportunity.py              Four-category classification + evidence grounding
    confidence.py               Confidence score + deterministic calibration
    analyzer.py                 One combined, cached analysis per professor

  backend/
    store.py                    SQLite scan history/status
    scan_manager.py             Crawl -> AI -> JSON -> PDF orchestration, retries
    api.py                      FastAPI routes and static frontend

  reporting/
    json_report.py              Validated UTF-8 JSON output
    pdf_report.py               ReportLab cover, summary, directory, profiles,
                                findings, methodology, headers/footers/links

  frontend/
    index.html                  Homepage, scan form, progress, dashboard, history
    styles.css                  Responsive professional styling
    app.js                      Polling, filtering, sorting, downloads, retry

tests/
  fixtures/                     Offline HTML fixtures
  test_url_validation.py
  test_extraction.py
  test_spider_dedup.py
  test_ai_grounding.py
  test_reports.py
  test_error_handling.py
  test_e2e_live.py              Opt-in live ODU scan
```

### Crawling behavior

- Scrapy is the primary crawler and is invoked programmatically through Python.
- Each scan runs in a child process because Twisted's reactor is single-use.
- The spider starts at the submitted URL, follows relevance-scored links, and
  prioritizes directory/profile pages.
- When the submitted URL is a department page, the crawl focuses on that
  department while still allowing clearly academic external links (personal
  sites, labs, research groups) discovered from professor profiles.
- External domains are capped and scored independently. Social networks and
  scholarly profile silos (Google Scholar, ORCID, ResearchGate, DBLP, etc.) are
  retained as profile links but are not crawled.
- robots.txt is respected, a request delay and auto-throttle are used, URLs are
  deduplicated, redirects/timeouts are handled, and page/domain/runtime caps
  prevent loops and runaway crawls.
- Inaccessible pages are recorded in `crawl.errors` and `crawl.manual_review`.
- Duplicate professors are merged by normalized name, middle-initial variants,
  email, profile URL, and name-token variants.
- Non-academic staff are excluded when their title clearly indicates an
  administrative/teaching-assistant role.
- Playwright is optional and is used only for pages marked as JavaScript-suspect.
  If it is not installed, the server-rendered crawl is preserved with a warning.

### AI behavior and guardrails

Each professor gets one grounded analysis request containing:

- explicit research interests, methods, technologies, projects, labs, and links
- publication titles/years/venues
- profile excerpt
- verbatim opportunity evidence candidates, with source URLs, dates, and recency

The local model returns a research summary, publication themes, one of four
opportunity categories, and a confidence score.

Guardrails:

- The model may only cite supplied evidence candidates. Citations with a
  fabricated quotation are discarded.
- Category 1 (confirmed opening) or 2 (actively recruiting) requires grounded
  positive evidence. Without it, the assessment is downgraded to category 3, or
  category 4 when no evidence exists.
- Confidence is capped when evidence is missing, outdated, or undated. It
  measures evidence strength, not the probability of acceptance.
- A high confidence score never by itself means an open position.
- Completed analyses are cached in `cache/ai_cache.sqlite3`.
- If Ollama is unavailable, the crawl is preserved, JSON/PDF are still generated
  with explicit "not analyzed" records, and **Retry AI analysis** reruns only the
  AI/report stages.

### Opportunity categories

1. **Confirmed open position** — explicit public evidence of an available
   undergraduate research position.
2. **Actively recruiting / welcoming students** — explicit invitation to students
   without a confirmed specific vacancy.
3. **Potential opportunity** — no explicit opening or recruitment statement, but
   a respectful inquiry is worthwhile.
4. **No opportunity information found** — insufficient public evidence.

Absence of public information does not mean absence of opportunities.

---

## API

The backend is a local FastAPI application.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Web interface |
| GET | `/api/health` | App/Ollama/model/defaults |
| POST | `/api/scans` | Start a scan |
| GET | `/api/scans` | Previous scans |
| GET | `/api/scans/{id}` | Live progress/status |
| GET | `/api/scans/{id}/results` | Full JSON result |
| POST | `/api/scans/{id}/retry-ai` | Retry AI + regenerate reports |
| GET | `/api/scans/{id}/download/json` | Download comprehensive JSON |
| GET | `/api/scans/{id}/download/pdf` | Download PDF report |

Interactive API docs: <http://127.0.0.1:8765/api/docs>

Start a scan from the command line:

```bash
curl -X POST http://127.0.0.1:8765/api/scans \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.cs.odu.edu/","max_pages":100,"max_depth":3,"request_delay":1.0}'
```

Private/loopback scan targets are rejected by default as an SSRF guard.

---

## Testing

Run the offline suite:

```bash
python -m pytest -q
```

The suite uses saved HTML fixtures and mocked/fake AI responses. It covers:

- URL validation and normalization
- professor extraction
- duplicate detection / middle-initial merging
- research interest and methodology extraction
- publication extraction
- opportunity classification and evidence grounding
- confidence scoring and caps
- JSON generation and UTF-8 validity
- PDF generation and inclusion of every professor
- Ollama-unavailable error handling
- API smoke tests and scan-history persistence

Run the live end-to-end ODU scan:

```bash
RUN_LIVE_E2E=1 URD_E2E_MAX_PAGES=35 python -m pytest tests/test_e2e_live.py -q
```

The live test verifies that the scan completes, the JSON and PDF exist, every
professor in JSON appears in the PDF, and the AI status is reported honestly.

### Verified results in this environment

- Offline suite: **39 passed, 1 skipped** (the live pytest test is opt-in).
- Normal launch: `python main.py` started the server, returned health 200,
  selected `/Applications/Google Chrome.app/...`, and logged
  `Browser launch method: chrome`. The favicon endpoint returns 204 with no body,
  so the browser's automatic request does not log a server exception.
- Final browser end-to-end scan (`https://www.cs.odu.edu/`, `max_pages=30`,
  2026-11-18, scan `scan_2026-11-18_142735`):
  - The URL was entered and the form was submitted in Chrome; the progress
    dashboard advanced through crawl, AI, JSON, and PDF stages.
  - **47 professors identified** and **47 analyzed by Ollama**
    (`llama3.2:latest`), with 0 analysis failures.
  - 30 pages crawled, 14 publications, 7 evidence snippets, 0 crawl errors,
    6 manual-review records.
  - 0 confirmed openings, 0 actively recruiting, 9 potential opportunities,
    38 with no opportunity information found.
  - The results dashboard rendered all 47 expandable cards and six summary
    metrics. Searching `Zeil` returned exactly one result; searching `Sympson`
    returned zero.
  - No duplicate normalized names remained. The administrative
    `Bill Sympson` record was excluded with reason
    `excluded_non_academic_person` for the title
    `Faculty Affairs & Strategic Initiatives`.
  - JSON and PDF download links were live and both endpoints returned HTTP 200;
    all 47 JSON professors appeared in the 28-page PDF.
  - JSON: `outputs/scan_2026-11-18_142735/research_results.json` (214,286 bytes)
  - PDF: `outputs/scan_2026-11-18_142735/research_report.pdf` (87,967 bytes)
- Earlier verification scans, including `outputs/scan_2026-11-18_140616/`, remain
  in the local history. They predate the final duplicate and staff-title fixes
  and are not the final verification result; the 47-professor scan above is.

The ODU scan shows why the evidence rules matter: most public profiles contain
research descriptions but no explicit undergraduate opportunity statement, so the
honest classification is category 4 rather than an invented "open position".

---

## Configuration

Edit `config.yaml`:

```yaml
app:
  host: 127.0.0.1
  port: 8765
  open_browser: true
  chrome_path: ""

crawl:
  max_depth: 3
  max_pages: 100
  max_external_domains: 20
  request_delay: 1.0
  download_timeout: 25
  max_runtime_seconds: 1200
  use_playwright: true

ollama:
  base_url: "http://127.0.0.1:11434"
  model: "llama3.2:latest"
  timeout_seconds: 300
  temperature: 0.1
  num_ctx: 8192
  num_predict: 1100
  max_concurrent_requests: 2
  cache_path: "cache/ai_cache.sqlite3"

output:
  directory: "outputs"
```

Environment overrides: `URD_HOST`, `URD_PORT`, `OLLAMA_BASE_URL`,
`OLLAMA_MODEL`.

---

## Troubleshooting

**"Ollama is not running"**
```bash
ollama serve
ollama list
```

**"Configured model is not installed"**
```bash
ollama pull llama3.2:latest
```
Never change the model name silently; update `config.yaml` if you want a different
model.

**Port already in use**

`main.py` automatically tries the next free port and prints the chosen URL. You can
also pass `--port`.

**Chrome does not open**

The launcher tries standard macOS, Windows, and Linux Chrome paths, then the
default browser. You can set `app.chrome_path` in `config.yaml` or open the printed
localhost URL manually.

**PDF generation fails**

The JSON report is retained, the scan status becomes `completed_with_errors`, and
the error is logged in `logs/app.log`. The JSON download remains available.

**JavaScript-heavy sites**

Install the optional fallback:
```bash
python -m pip install playwright
playwright install chromium
```
Playwright is only used for pages the normal crawl marked as JavaScript-suspect.

**A scan is very large**

The default 100-page / 20-domain limit can take several minutes, especially with
local AI analysis. Reduce maximum pages or external domains in **Crawl settings**.
Completed AI analyses are cached and reused across scans.

---

## Limitations

- Only publicly accessible pages are analyzed. Login-gated, private, or
  unadvertised opportunities cannot be discovered.
- Absence of information is not evidence that no opportunity exists.
- AI summaries and classifications can be wrong; the JSON/PDF retain source URLs
  and quotations for manual verification.
- Publication coverage depends on what each profile page explicitly lists. The
  crawler does not fabricate publications or infer them from author names.
- External scholarly profiles are collected as links but not scraped, to respect
  site terms and avoid unreliable scraping.
- JavaScript rendering is optional and best-effort.
- The application does not send email or contact faculty; it produces a research
  shortlist for the user.
- A scan is a snapshot of public pages at the time it runs; dates and recency are
  recorded when the source exposes them.

---

## Privacy and responsible use

- All crawling and AI inference happen locally.
- No API keys or cloud AI services are used.
- The server binds to `127.0.0.1` by default.
- robots.txt is respected.
- Requests are delayed and capped.
- Source attribution is retained throughout the JSON and PDF.

Use the output as a starting point for respectful, personalized inquiries to
faculty—not as an authoritative statement from the university.
