(function () {
  "use strict";

  const STAGES = [
    ["initializing", "Initializing"],
    ["accessing", "Accessing submitted website"],
    ["discovering", "Discovering relevant pages"],
    ["identifying", "Identifying professors"],
    ["extracting", "Extracting research information"],
    ["publications", "Collecting publications"],
    ["ai_analysis", "Running Ollama analysis"],
    ["generating_json", "Generating JSON"],
    ["generating_pdf", "Generating PDF"],
    ["completed", "Completed"],
  ];

  const CATEGORY_LABELS = {
    1: "Confirmed open position",
    2: "Actively recruiting / welcoming students",
    3: "Potential opportunity",
    4: "No opportunity information found",
  };

  const state = {
    scanId: null,
    pollTimer: null,
    polling: false,
    pollFailures: 0,
    result: null,
    currentStatus: null,
    defaultsLoaded: false,
  };

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function safeUrl(value) {
    if (!value) return "";
    try {
      const parsed = new URL(String(value), window.location.href);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.href;
    } catch (error) {
      return "";
    }
    return "";
  }

  function link(url, label) {
    const href = safeUrl(url);
    if (!href) return escapeHtml(label || url || "Not available");
    return '<a href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' +
      escapeHtml(label || url) + "</a>";
  }

  function mailLink(email) {
    if (!email) return "";
    const clean = String(email).replace(/[^A-Za-z0-9._%+@-]/g, "");
    if (!clean) return "";
    return '<a href="mailto:' + escapeHtml(clean) + '">' + escapeHtml(email) + "</a>";
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return date.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  }

  function api(path, options) {
    const config = Object.assign({ headers: { "Content-Type": "application/json" } }, options || {});
    return fetch(path, config).then(function (response) {
      return response.json().catch(function () { return null; }).then(function (data) {
        if (!response.ok) {
          const message = data && data.detail ? data.detail : "Request failed (" + response.status + ").";
          throw new Error(message);
        }
        return data;
      });
    });
  }

  function showFormError(message) {
    const box = $("#form-error");
    if (!message) {
      box.textContent = "";
      box.classList.add("hidden");
      return;
    }
    box.textContent = message;
    box.classList.remove("hidden");
  }

  function setFormBusy(busy) {
    const button = $("#run-button");
    button.disabled = busy;
    $(".button-label", button).textContent = busy ? "Scanning…" : "Run Scan";
  }

  function renderHealth(health) {
    const ollama = health.ollama || {};
    const pill = $("#ai-pill");
    pill.className = "status-pill";
    const ready = Boolean(ollama.available && ollama.model_installed);
    if (ready) {
      pill.classList.add("is-ready");
      pill.textContent = "Ollama ready · " + (ollama.model || "local model");
    } else if (ollama.available) {
      pill.classList.add("is-warning");
      pill.textContent = "Ollama model missing";
    } else {
      pill.classList.add("is-offline");
      pill.textContent = "Ollama offline";
    }

    const banner = $("#ai-banner");
    if (ready) {
      banner.classList.add("hidden");
    } else {
      banner.classList.remove("hidden");
      $("#ai-banner-title").textContent = ollama.available
        ? "Ollama is running, but the model is missing"
        : "Ollama is not running";
      $("#ai-banner-message").textContent = ollama.message || "Local AI analysis is unavailable.";
      const list = $("#ai-banner-instructions");
      list.innerHTML = "";
      (ollama.setup_instructions || []).forEach(function (instruction) {
        const item = document.createElement("li");
        item.textContent = instruction;
        list.appendChild(item);
      });
    }

    const defaults = health.defaults || {};
    if (!state.defaultsLoaded) {
      if (defaults.max_depth != null) $("#max_depth").value = defaults.max_depth;
      if (defaults.max_pages != null) $("#max_pages").value = defaults.max_pages;
      if (defaults.max_external_domains != null) $("#max_external_domains").value = defaults.max_external_domains;
      if (defaults.request_delay != null) $("#request_delay").value = defaults.request_delay;
      state.defaultsLoaded = true;
    }
  }

  function initStages() {
    const list = $("#stage-list");
    list.innerHTML = "";
    STAGES.forEach(function (stage, index) {
      const item = document.createElement("li");
      item.dataset.stage = stage[0];
      item.innerHTML = '<span class="stage-dot">' + (index + 1) + "</span><span>" + escapeHtml(stage[1]) + "</span>";
      list.appendChild(item);
    });
  }

  function renderStages(activeStage, status) {
    const currentIndex = STAGES.findIndex(function (stage) { return stage[0] === activeStage; });
    $$("#stage-list li").forEach(function (item, index) {
      item.classList.remove("is-done", "is-active", "is-failed");
      if (status === "failed") {
        if (index === STAGES.length - 1) item.classList.add("is-failed");
        return;
      }
      if (status === "completed" || activeStage === "completed") {
        item.classList.add("is-done");
        return;
      }
      if (currentIndex === -1) return;
      if (index < currentIndex) item.classList.add("is-done");
      else if (index === currentIndex) item.classList.add("is-active");
    });
  }

  function renderProgress(status) {
    state.currentStatus = status;
    const section = $("#progress-section");
    section.classList.remove("hidden");
    const progress = Math.max(0, Math.min(100, Number(status.progress) || 0));
    const label = status.status === "failed"
      ? (status.error || status.message || "Scan failed")
      : (status.message || "Working…");
    $("#progress-status").textContent = label;

    if (status.status === "failed") {
      $("#progress-section").classList.add("has-failure");
    } else {
      $("#progress-section").classList.remove("has-failure");
    }

    $("#progress-percent").textContent = progress + "%";
    $("#progress-bar").style.width = progress + "%";
    const track = $(".progress-track");
    track.setAttribute("aria-valuenow", String(progress));

    const counters = status.counters || {};
    $("#counter-pages").textContent = counters.pages || 0;
    $("#counter-professors").textContent = counters.professors || 0;
    $("#counter-publications").textContent = counters.publications || 0;
    $("#counter-analyzed").textContent = counters.analyzed || 0;
    $("#counter-warnings").textContent = counters.warnings || 0;
    $("#counter-errors").textContent = counters.errors || 0;

    renderStages(status.stage, status.status);
    const ai = status.ai || {};
    if (ai.status && ai.status !== "not_run") {
      $("#progress-ai-note").textContent = "Ollama · " + (ai.model || "local model") + " · " + ai.status +
        (ai.message ? " — " + ai.message : "");
    } else {
      $("#progress-ai-note").textContent = "";
    }
  }

  function confidenceOf(professor) {
    const value = professor.opportunity ? professor.opportunity.confidence : null;
    return typeof value === "number" ? value : null;
  }

  function categoryOf(professor) {
    const value = professor.opportunity ? professor.opportunity.category : null;
    return typeof value === "number" ? value : null;
  }

  function categoryBadge(professor) {
    const category = categoryOf(professor);
    const label = (professor.opportunity && professor.opportunity.category_label) ||
      CATEGORY_LABELS[category] || "Not analyzed";
    return '<span class="badge cat-' + (category || "none") + '">' + escapeHtml(label) + "</span>";
  }

  function uniqueList(values) {
    const seen = {};
    const result = [];
    (values || []).forEach(function (value) {
      if (typeof value !== "string") return;
      const clean = value.trim();
      if (!clean) return;
      const key = clean.toLowerCase();
      if (seen[key]) return;
      seen[key] = true;
      result.push(clean);
    });
    return result;
  }

  function researchInterests(professor) {
    const research = professor.research || {};
    return uniqueList((research.interests || []).concat(research.ai_interests || []));
  }

  function professorCard(professor) {
    const research = professor.research || {};
    const opportunity = professor.opportunity || {};
    const confidence = confidenceOf(professor);
    const category = categoryOf(professor);
    const interests = researchInterests(professor);
    const subtitle = [professor.title, professor.department].filter(Boolean).join(" · ") || "Faculty";

    const metaLinks = [];
    if (professor.email) metaLinks.push(mailLink(professor.email));
    if (professor.profile_url) metaLinks.push(link(professor.profile_url, "Faculty profile"));
    if (professor.personal_website) metaLinks.push(link(professor.personal_website, "Personal website"));
    const labLinks = research.lab_links || [];
    if (labLinks.length && labLinks[0].url) {
      metaLinks.push(link(labLinks[0].url, labLinks[0].label || "Laboratory"));
    }
    (professor.links && professor.links.academic_profiles ? professor.links.academic_profiles : [])
      .slice(0, 2).forEach(function (profile) {
        if (profile.url) metaLinks.push(link(profile.url, profile.label || "Academic profile"));
      });

    let summaryHtml = "";
    if (research.summary) {
      summaryHtml = String(research.summary).split(/\n{2,}/).map(function (paragraph) {
        return "<p>" + escapeHtml(paragraph).replace(/\n/g, "<br>") + "</p>";
      }).join("");
    } else {
      summaryHtml = "<p>AI analysis was not completed for this professor. " +
        "The collected profile information and sources are preserved below and in the JSON report.</p>";
    }

    let interestsHtml = "";
    if (interests.length) {
      interestsHtml = '<ul class="pill-list">' + interests.slice(0, 12).map(function (interest) {
        return "<li>" + escapeHtml(interest) + "</li>";
      }).join("") + "</ul>";
    }

    const methods = uniqueList((research.methodologies || []).concat(research.ai_methodologies || []));
    const technologies = uniqueList((research.technologies || []).concat(research.ai_technologies || []));
    const methodHtml = methods.length
      ? "<p><strong>Methods:</strong> " + escapeHtml(methods.slice(0, 8).join("; ")) + "</p>" : "";
    const techHtml = technologies.length
      ? "<p><strong>Technologies:</strong> " + escapeHtml(technologies.slice(0, 10).join("; ")) + "</p>" : "";

    let publicationHtml = "";
    const publications = professor.publications || [];
    if (publications.length) {
      publicationHtml = '<ul class="publication-list">' + publications.slice(0, 6).map(function (publication) {
        const title = publication.url
          ? link(publication.url, publication.title || "Untitled publication")
          : escapeHtml(publication.title || "Untitled publication");
        const year = publication.year ? '<span class="publication-year"> (' + escapeHtml(publication.year) + ")</span>" : "";
        const venue = publication.venue ? " — <em>" + escapeHtml(publication.venue) + "</em>" : "";
        return "<li>" + title + year + venue + "</li>";
      }).join("") + "</ul>";
      if (publications.length > 6) {
        publicationHtml += '<p class="ai-note">' + (publications.length - 6) + " additional publications are listed in the JSON report.</p>";
      }
    } else {
      publicationHtml = "<p>No publications were collected from the crawled pages.</p>";
    }

    let evidenceHtml = "";
    const evidence = opportunity.evidence || [];
    if (evidence.length) {
      evidenceHtml = '<ul class="evidence-list">' + evidence.slice(0, 3).map(function (item) {
        const date = item.date || "date unknown";
        const current = item.current === true ? "current" : (item.current === false ? "possibly outdated" : "recency unknown");
        const explanation = item.explanation
          ? '<span class="evidence-explanation">' + escapeHtml(item.explanation) + "</span>" : "";
        return '<li><span class="evidence-quote">“' + escapeHtml(item.quote || "") + "”</span>" +
          '<span class="evidence-source">' + link(item.url, "Source") + " · " + escapeHtml(date) + " · " + escapeHtml(current) + "</span>" +
          explanation + "</li>";
      }).join("") + "</ul>";
    } else {
      evidenceHtml = "<p>No public evidence of an undergraduate research opening or recruitment statement was found. " +
        "Absence of information does not mean absence of opportunities.</p>";
    }

    const assessmentNote = opportunity.assessment_status === "adjusted"
      ? '<p class="ai-note">The assessment was adjusted conservatively after evidence grounding.</p>' : "";
    const aiNote = research.ai_generated
      ? '<p class="ai-note">AI-generated summary grounded in the crawled sources listed below. ' +
        "Verify details with the faculty member.</p>" : "";

    return '<details class="professor-card">' +
      "<summary>" +
        '<div class="prof-title"><h3>' + escapeHtml(professor.name || "Unknown professor") + "</h3>" +
        '<p class="prof-subtitle">' + escapeHtml(subtitle) + "</p></div>" +
        '<div class="prof-badges">' + categoryBadge(professor) +
        (confidence != null
          ? '<span class="confidence"><strong>' + confidence + "</strong><span>confidence</span></span>"
          : '<span class="confidence none">—</span>') +
        "</div>" +
      "</summary>" +
      '<div class="prof-body">' +
        (metaLinks.length ? '<div class="prof-links">' + metaLinks.join("") + "</div>" : "") +
        '<section class="prof-section"><h4>Research</h4>' + summaryHtml +
          (interestsHtml ? '<div style="margin-top:8px">' + interestsHtml + "</div>" : "") +
          methodHtml + techHtml + aiNote + "</section>" +
        '<section class="prof-section"><h4>Publications</h4>' + publicationHtml +
          (research.publication_analysis ? "<p>" + escapeHtml(research.publication_analysis) + "</p>" : "") +
        "</section>" +
        '<section class="opportunity-box"><h4>Undergraduate research opportunity</h4>' +
          "<p>" + categoryBadge(professor) +
          (confidence != null ? ' <span class="ai-note" style="display:inline">' + confidence + "/100 evidence-confidence</span>" : "") + "</p>" +
          (opportunity.explanation ? '<p class="opportunity-explanation">' + escapeHtml(opportunity.explanation) + "</p>" : "") +
          (opportunity.confidence_explanation ? '<p class="confidence-note">' + escapeHtml(opportunity.confidence_explanation) + "</p>" : "") +
          assessmentNote + evidenceHtml +
        "</section>" +
        '<section class="prof-section"><h4>Sources</h4><p>Profile and evidence URLs are linked above. ' +
          "Full source tracking is included in the JSON report.</p></section>" +
      "</div>" +
    "</details>";
  }

  function filteredProfessors() {
    if (!state.result) return [];
    const query = ($("#search").value || "").trim().toLowerCase();
    const interestQuery = ($("#interest-filter").value || "").trim().toLowerCase();
    const categoryValue = $("#category-filter").value;
    const sortValue = $("#sort-select").value;

    let professors = (state.result.professors || []).filter(function (professor) {
      const name = (professor.name || "").toLowerCase();
      if (query && name.indexOf(query) === -1) return false;
      const category = categoryOf(professor);
      if (categoryValue === "none" && category !== null) return false;
      if (categoryValue !== "all" && categoryValue !== "none" && String(category) !== categoryValue) return false;
      if (interestQuery) {
        const haystack = researchInterests(professor).concat([
          (professor.research || {}).summary || "",
          ((professor.research || {}).publication_topics || []).join(" "),
          ((professor.research || {}).publication_analysis || ""),
          ((professor.research || {}).projects || []).join(" "),
        ]).join(" ").toLowerCase();
        if (haystack.indexOf(interestQuery) === -1) return false;
      }
      return true;
    });

    professors.sort(function (a, b) {
      if (sortValue === "name") return (a.name || "").localeCompare(b.name || "");
      if (sortValue === "category") {
        return (categoryOf(a) || 99) - (categoryOf(b) || 99) || (a.name || "").localeCompare(b.name || "");
      }
      const aConfidence = confidenceOf(a);
      const bConfidence = confidenceOf(b);
      if (aConfidence == null && bConfidence == null) return (a.name || "").localeCompare(b.name || "");
      if (aConfidence == null) return 1;
      if (bConfidence == null) return -1;
      return sortValue === "confidence-asc" ? aConfidence - bConfidence : bConfidence - aConfidence;
    });
    return professors;
  }

  function renderProfessorList() {
    if (!state.result) return;
    const all = state.result.professors || [];
    const professors = filteredProfessors();
    const list = $("#professor-list");
    list.innerHTML = professors.map(professorCard).join("");
    $("#result-count").textContent = "Showing " + professors.length + " of " + all.length + " professors";
    $("#empty-results").classList.toggle("hidden", professors.length !== 0);
  }

  function setDownloads(scanId, downloads) {
    const jsonLink = $("#download-json");
    const pdfLink = $("#download-pdf");
    if (downloads && downloads.json) {
      jsonLink.href = "/api/scans/" + encodeURIComponent(scanId) + "/download/json";
      jsonLink.classList.remove("hidden");
    } else {
      jsonLink.classList.add("hidden");
    }
    if (downloads && downloads.pdf) {
      pdfLink.href = "/api/scans/" + encodeURIComponent(scanId) + "/download/pdf";
      pdfLink.classList.remove("hidden");
    } else {
      pdfLink.classList.add("hidden");
    }
  }

  function renderSummary(summary) {
    const metrics = [
      ["Professors identified", summary.professors_identified || 0, ""],
      ["Professors analyzed", summary.professors_analyzed || 0, ""],
      ["Confirmed open positions", summary.confirmed_open || 0, "accent"],
      ["Actively recruiting", summary.actively_recruiting || 0, ""],
      ["Potential opportunities", summary.potential_opportunity || 0, ""],
      ["Insufficient information", summary.no_information || 0, ""],
    ];
    $("#summary-grid").innerHTML = metrics.map(function (metric) {
      return '<div class="summary-card ' + metric[2] + '"><span class="summary-value">' + metric[1] +
        '</span><span class="summary-label">' + escapeHtml(metric[0]) + "</span></div>";
    }).join("");
  }

  function renderResultsAiBanner(result) {
    const ai = (result.scan || {}).ai || {};
    const banner = $("#results-ai-banner");
    if (ai.status === "complete") {
      banner.classList.add("hidden");
      return;
    }
    banner.classList.remove("hidden");
    $("#results-ai-title").textContent = ai.status === "skipped"
      ? "AI analysis skipped"
      : "AI analysis incomplete";
    $("#results-ai-message").textContent = ai.message || "Some professors do not have an AI assessment.";
    const list = $("#results-ai-instructions");
    list.innerHTML = "";
    (ai.setup_instructions || []).forEach(function (instruction) {
      const item = document.createElement("li");
      item.textContent = instruction;
      list.appendChild(item);
    });
    const retry = $("#retry-ai-button");
    retry.classList.toggle("hidden", (result.professors || []).length === 0);
    retry.disabled = false;
    retry.textContent = "Retry AI analysis";
  }

  function renderResults(result, status) {
    state.result = result;
    const scan = result.scan || {};
    $("#results-section").classList.remove("hidden");
    $("#results-title").textContent = "Results dashboard";
    $("#results-url").textContent = scan.url || "";
    const bits = [];
    if (result.university) bits.push(result.university);
    if (result.department) bits.push(result.department);
    if (scan.completed_at) bits.push("Completed " + formatDate(scan.completed_at));
    const stats = scan.stats || {};
    if (stats.pages_visited != null) bits.push(stats.pages_visited + " pages crawled");
    $("#results-meta").textContent = bits.join(" · ");
    renderSummary(scan.summary || {});
    setDownloads(scan.id, status && status.downloads ? status.downloads : { json: true, pdf: true });
    renderResultsAiBanner(result);
    renderProfessorList();
  }

  function startPolling(scanId) {
    state.scanId = scanId;
    state.pollFailures = 0;
    if (state.pollTimer) window.clearInterval(state.pollTimer);
    pollScan();
    state.pollTimer = window.setInterval(pollScan, 1200);
  }

  async function pollScan() {
    if (!state.scanId || state.polling) return;
    state.polling = true;
    try {
      const status = await api("/api/scans/" + encodeURIComponent(state.scanId));
      state.pollFailures = 0;
      renderProgress(status);
      if (status.status === "completed" || status.status === "completed_with_errors") {
        stopPolling();
        setFormBusy(false);
        await loadResults(state.scanId, status);
        loadHistory();
      } else if (status.status === "failed") {
        stopPolling();
        setFormBusy(false);
        renderProgress(status);
        loadHistory();
      }
    } catch (error) {
      state.pollFailures += 1;
      if (state.pollFailures >= 5) {
        stopPolling();
        setFormBusy(false);
        showFormError("Lost contact with the local server: " + error.message);
      }
    } finally {
      state.polling = false;
    }
  }

  function stopPolling() {
    if (state.pollTimer) window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  async function loadResults(scanId, status) {
    try {
      const result = await api("/api/scans/" + encodeURIComponent(scanId) + "/results");
      renderResults(result, status || state.currentStatus);
      const section = $("#results-section");
      if (section.getBoundingClientRect().top < 0) {
        section.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch (error) {
      showFormError("The scan completed, but the results could not be loaded: " + error.message);
    }
  }

  async function runScan(event) {
    event.preventDefault();
    showFormError("");
    const url = $("#url").value.trim();
    if (!url) {
      showFormError("Enter a university webpage URL to begin.");
      $("#url").focus();
      return;
    }
    setFormBusy(true);
    const payload = {
      url: url,
      max_depth: Number($("#max_depth").value),
      max_pages: Number($("#max_pages").value),
      max_external_domains: Number($("#max_external_domains").value),
      request_delay: Number($("#request_delay").value),
    };
    try {
      const status = await api("/api/scans", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      $("#results-section").classList.add("hidden");
      $("#history-list").classList.remove("hidden");
      renderProgress(status);
      $("#progress-section").scrollIntoView({ behavior: "smooth", block: "start" });
      startPolling(status.id);
    } catch (error) {
      setFormBusy(false);
      showFormError(error.message);
    }
  }

  async function retryAi() {
    if (!state.scanId) return;
    const button = $("#retry-ai-button");
    button.disabled = true;
    button.textContent = "Retrying…";
    try {
      const status = await api("/api/scans/" + encodeURIComponent(state.scanId) + "/retry-ai", {
        method: "POST",
        body: JSON.stringify({ force_refresh: false }),
      });
      showFormError("");
      renderProgress(status);
      $("#progress-section").scrollIntoView({ behavior: "smooth", block: "start" });
      startPolling(state.scanId);
    } catch (error) {
      button.disabled = false;
      button.textContent = "Retry AI analysis";
      $("#results-ai-message").textContent = error.message;
      $("#results-ai-banner").classList.remove("hidden");
    }
  }

  function renderHistory(data) {
    const list = $("#history-list");
    const scans = (data && data.scans) || [];
    if (!scans.length) {
      list.innerHTML = '<p class="empty-state">No scans yet. Start with a university URL above.</p>';
      return;
    }
    list.innerHTML = scans.map(function (scan) {
      const summary = scan.summary || {};
      const professors = summary.professors_identified != null ? summary.professors_identified : (scan.counters || {}).professors || 0;
      const statusClass = ["completed", "completed_with_errors", "failed", "running", "queued"].indexOf(scan.status) !== -1
        ? (scan.status === "completed_with_errors" ? "completed" : scan.status) : "";
      return '<button class="history-item" type="button" data-scan-id="' + escapeHtml(scan.id) + '">' +
        '<span><span class="history-url">' + escapeHtml(scan.url) + "</span>" +
        '<span class="history-meta">' + escapeHtml(formatDate(scan.created_at)) + " · " +
        escapeHtml((scan.message || "").slice(0, 100)) + "</span></span>" +
        '<span class="history-right"><span class="status-chip ' + statusClass + '">' + escapeHtml(scan.status) + "</span>" +
        '<span class="history-count">' + escapeHtml(professors) + " professors</span></span></button>";
    }).join("");
    $$(".history-item", list).forEach(function (button) {
      button.addEventListener("click", function () {
        openScan(button.dataset.scanId);
      });
    });
  }

  async function loadHistory() {
    try {
      const data = await api("/api/scans?limit=12");
      renderHistory(data);
    } catch (error) {
      $("#history-list").innerHTML = '<p class="empty-state">Could not load previous scans: ' + escapeHtml(error.message) + "</p>";
    }
  }

  async function openScan(scanId) {
    state.scanId = scanId;
    showFormError("");
    try {
      const status = await api("/api/scans/" + encodeURIComponent(scanId));
      renderProgress(status);
      if (status.status === "completed" || status.status === "completed_with_errors") {
        await loadResults(scanId, status);
        setFormBusy(false);
      } else if (status.status === "running" || status.status === "queued") {
        setFormBusy(true);
        startPolling(scanId);
      } else {
        setFormBusy(false);
      }
      $("#progress-section").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      showFormError("Could not open that scan: " + error.message);
    }
  }

  async function loadHealth() {
    try {
      const health = await api("/api/health");
      renderHealth(health);
      return health;
    } catch (error) {
      $("#ai-pill").className = "status-pill is-offline";
      $("#ai-pill").textContent = "Server unreachable";
      return null;
    }
  }

  function bindEvents() {
    $("#scan-form").addEventListener("submit", runScan);
    ["search", "category-filter", "interest-filter", "sort-select"].forEach(function (id) {
      $("#" + id).addEventListener("input", renderProfessorList);
      $("#" + id).addEventListener("change", renderProfessorList);
    });
    $("#retry-ai-button").addEventListener("click", retryAi);
    $("#refresh-history").addEventListener("click", loadHistory);
  }

  document.addEventListener("DOMContentLoaded", function () {
    initStages();
    bindEvents();
    loadHealth();
    loadHistory();
    const urlInput = $("#url");
    if (urlInput) urlInput.focus();
  });
})();
