const API = "";
const WS_URL = `ws://${location.host}/ws`;

const id = new URLSearchParams(location.search).get("id");
if (!id) location.href = "/";

// WebSocket (just for status pill + live banner if needed)
const ws = new WebSocket(WS_URL);
ws.onopen = () => {
  document.getElementById("ws-status").textContent = "live";
  document.getElementById("ws-status").className = "status-pill connected";
};
ws.onclose = () => {
  document.getElementById("ws-status").textContent = "offline";
  document.getElementById("ws-status").className = "status-pill error";
};

async function loadSummary() {
  try {
    const [filingRes, summaryRes] = await Promise.all([
      fetch(`${API}/api/companies/${id}`),
      fetch(`${API}/api/companies/${id}/summary`),
    ]);

    if (!filingRes.ok || !summaryRes.ok) {
      document.getElementById("summary-header").innerHTML =
        `<p style="color:var(--red)">Summary not found.</p>`;
      return;
    }

    const filing = await filingRes.json();
    const summary = await summaryRes.json();

    renderHeader(filing, summary);
    renderBody(summary, filing);

    document.title = `${filing.company} — The AfterCall`;
    document.getElementById("summary-body").style.display = "block";
  } catch (err) {
    document.getElementById("summary-header").innerHTML =
      `<p style="color:var(--red)">Failed to load: ${err.message}</p>`;
  }
}

function renderHeader(filing, summary) {
  document.getElementById("summary-header").innerHTML = `
    <h1>${filing.company}</h1>
    <div class="summary-meta">
      <span class="meta-badge">${filing.exchange}</span>
      <span>${filing.symbol || ""}</span>
      <span>Filed: ${filing.filed_at}</span>
      <span style="color:var(--text-muted)">AI summary generated ${formatDate(summary.generated_at)}</span>
    </div>
  `;
}

function renderBody(summary, filing) {
  document.getElementById("tldr").textContent = summary.tldr || "—";

  renderList("management-commentary", summary.management_commentary);
  renderList("guidance", summary.guidance);
  renderList("segments", summary.segment_performance);
  renderList("risks", summary.risks_and_concerns);
  renderMetrics(summary.key_metrics || []);
  renderQA(summary.qa_highlights || []);

  document.getElementById("source-pdf").href = filing.source_url || "#";
  document.getElementById("source-transcript").href = `${API}/api/companies/${id}/transcript`;
  document.getElementById("source-markdown").href = `${API}/api/companies/${id}/summary/markdown`;
}

function renderList(elId, items) {
  const el = document.getElementById(elId);
  if (!items || items.length === 0) {
    el.innerHTML = "<li style='color:var(--text-muted)'>Not mentioned</li>";
    return;
  }
  el.innerHTML = items.map(i => `<li>${i}</li>`).join("");
}

function renderMetrics(metrics) {
  const tbody = document.getElementById("metrics-body");
  if (!metrics.length) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--text-muted)">No metrics extracted</td></tr>`;
    return;
  }
  tbody.innerHTML = metrics.map(m => `
    <tr>
      <td><strong>${m.metric || "—"}</strong></td>
      <td>${m.value || "—"}</td>
      <td>${m.period || "—"}</td>
      <td style="color:var(--text-muted)">${m.note || ""}</td>
    </tr>
  `).join("");
}

function renderQA(qas) {
  const el = document.getElementById("qa-list");
  if (!qas.length) {
    el.innerHTML = `<p style="color:var(--text-muted)">No Q&A highlights extracted</p>`;
    return;
  }
  el.innerHTML = qas.map(qa => `
    <div class="qa-item">
      <div class="qa-q"><strong>Q:</strong> ${qa.question || "—"}</div>
      <div class="qa-a"><strong>A:</strong> ${qa.answer || "—"}</div>
    </div>
  `).join("");
}

function formatDate(str) {
  if (!str) return "";
  try { return new Date(str).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }); }
  catch { return str; }
}

loadSummary();
