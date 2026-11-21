const API = "";
const WS_URL = `ws://${location.host}/ws`;

let ws;

function connectWS() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    document.getElementById("ws-status").textContent = "live";
    document.getElementById("ws-status").className = "status-pill connected";
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.event === "init") {
      renderCompanies(msg.companies);
    } else if (msg.event === "new-summary") {
      showLiveBanner(msg.company);
      // Reload companies to pick up the new one
      loadCompanies();
    }
  };

  ws.onclose = () => {
    document.getElementById("ws-status").textContent = "reconnecting...";
    document.getElementById("ws-status").className = "status-pill error";
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws.close();
}

async function loadCompanies() {
  try {
    const res = await fetch(`${API}/api/companies`);
    const companies = await res.json();
    renderCompanies(companies.map(c => ({
      filing_id: c.id,
      company: c.company,
      exchange: c.exchange,
      filed_at: c.filed_at,
      tldr: c.tldr,
    })));
  } catch (err) {
    console.error("Failed to load companies:", err);
  }
}

async function renderCompanies(companies) {
  const container = document.getElementById("companies");

  if (!companies || companies.length === 0) {
    container.innerHTML = `<div class="empty">No summaries yet. The pipeline is warming up — check back soon.</div>`;
    return;
  }

  // For each company, fetch summary to get tldr if not already present
  const cards = await Promise.all(companies.map(async (c) => {
    let tldr = c.tldr || "";
    if (!tldr && c.filing_id) {
      try {
        const r = await fetch(`${API}/api/companies/${c.filing_id}/summary`);
        if (r.ok) {
          const data = await r.json();
          tldr = data.tldr || "";
        }
      } catch {}
    }
    return { ...c, tldr };
  }));

  container.innerHTML = cards.map(c => `
    <a class="company-card" href="summary.html?id=${c.filing_id}">
      <div class="card-exchange">${c.exchange}</div>
      <div class="card-name">${c.company}</div>
      ${c.tldr ? `<div class="card-tldr">${c.tldr}</div>` : ""}
      <div class="card-meta">${formatDate(c.filed_at)}</div>
    </a>
  `).join("");
}

function showLiveBanner(company) {
  const banner = document.getElementById("live-banner");
  document.getElementById("live-text").textContent = `New summary: ${company}`;
  banner.style.display = "flex";
  setTimeout(() => banner.style.display = "none", 8000);
}

function formatDate(str) {
  if (!str) return "";
  try {
    const d = new Date(str.replace(/(\d{2})-([A-Za-z]+)-(\d{4})/, "$2 $1 $3"));
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  } catch { return str; }
}

connectWS();
loadCompanies();
