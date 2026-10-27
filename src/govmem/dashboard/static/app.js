// Minimal dashboard: polls the REST API and renders memory, quarantine, decisions, audit.
const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(JSON.stringify(body));
  return body;
};
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const reviewer = () => $("reviewer").value || "rev-1";
const show = (el, obj) => { $(el).textContent = JSON.stringify(obj, null, 2); };
let lastVersions = {};

async function refresh() {
  try {
    const [h, s, pats, q, d, a, v] = await Promise.all([
      api("/api/health"), api("/api/memory/stats"), api("/api/patterns"), api("/api/quarantine"),
      api("/api/decisions?limit=15"), api("/api/audit?limit=40"), api("/api/audit/verify"),
    ]);
    $("health").textContent = `${h.status} · llm=${h.llm} · embedder=${h.embedder} · encoding=${h.encoding}`;
    $("s-count").textContent = s.pattern_count;
    $("s-bytes").textContent = `${s.pattern_bytes} / ${s.budget_bytes} B`;
    $("s-bar").style.width = `${Math.min(100, 100 * s.pattern_bytes / s.budget_bytes)}%`;
    $("s-rec").textContent = `${s.record_size_bytes} B (${s.encoding})`;
    $("s-q").textContent = s.quarantine_count;
    $("s-epi").textContent = `${s.episodic_count} (${s.episodic_raw_bytes} B)`;
    $("s-audit").textContent = v.ok ? `ok · ${v.events}` : `BROKEN @${v.first_bad_id}`;

    $("patterns").innerHTML = pats.map((p) => {
      const changed = lastVersions[p.id] !== undefined && lastVersions[p.id] !== p.version ? "changed" : "";
      lastVersions[p.id] = p.version;
      return `<tr class="${changed}"><td>${p.id}</td><td>${p.version}</td><td>${esc(p.action)}</td><td>${esc(p.resource_class)}</td>
      <td>${esc(p.context_key)}</td><td>${p.support}</td><td>${p.windows}</td><td>${p.risk.toFixed(3)}</td>
      <td>${p.ema_risk.toFixed(3)}</td><td>${p.reliability.toFixed(2)}</td><td>${p.usefulness.toFixed(2)}</td><td>${p.byte_size}</td>
      <td><button data-fb="${p.id}" data-o="harmful">harmful</button><button data-fb="${p.id}" data-o="benign">benign</button></td></tr>`;
    }).join("") || `<tr><td colspan="13" class="muted">no validated patterns yet — seed events or observe</td></tr>`;

    $("quarantine").innerHTML = q.map((c) => `<tr><td>${c.id}</td><td>${c.status}</td><td>${esc(c.action)}</td><td>${esc(c.resource_class)}</td>
      <td>${esc(c.context_key)}</td><td>${c.support}</td><td>${c.windows.length}</td>
      <td>${esc(Object.entries(c.sources).map(([k, n]) => `${k}×${n}`).join(", "))}</td><td>${(+c.validation_score).toFixed(3)}</td>
      <td>${c.flags.map((f) => `<span class="flag">${esc(f)}</span>`).join("")}</td>
      <td><button data-rv="${c.id}" data-v="approve">approve</button><button data-rv="${c.id}" data-v="reject">reject</button></td></tr>`).join("")
      || `<tr><td colspan="11" class="muted">empty</td></tr>`;

    $("decisions").innerHTML = d.map((x) => `<tr><td>${x.id}</td><td>${esc(x.request.action)}</td><td>${esc(x.request.resource)}</td>
      <td class="${x.base_decision}">${x.base_decision}</td><td class="${x.decision}">${x.decision}</td><td>${x.pattern_id ?? ""}</td>
      <td>${x.risk == null ? "" : (+x.risk).toFixed(3)}</td>
      <td>${x.pattern_id ? `<button data-dfb="${x.id}" data-o="harmful">H</button><button data-dfb="${x.id}" data-o="benign">B</button>` : ""}</td></tr>`).join("");

    $("audit").innerHTML = a.map((e) => `<li><b>#${e.id}</b> ${esc(e.event_type)} <span class="muted">${esc(e.entity_type)}:${esc(e.entity_id)} by ${esc(e.actor)}</span>
      <div class="muted">${esc(JSON.stringify(e.payload)).slice(0, 180)}</div></li>`).join("");
  } catch (err) { $("health").textContent = "error: " + err.message; }
}

document.addEventListener("click", async (ev) => {
  const t = ev.target;
  try {
    if (t.dataset.fb) show("ctl-out", await post("/api/feedback", { reviewer_id: reviewer(), outcome: t.dataset.o, pattern_id: +t.dataset.fb }));
    else if (t.dataset.dfb) show("ctl-out", await post("/api/feedback", { reviewer_id: reviewer(), outcome: t.dataset.o, decision_id: +t.dataset.dfb }));
    else if (t.dataset.rv) show("ctl-out", await post(`/api/quarantine/${t.dataset.rv}/review`, { reviewer_id: reviewer(), verdict: t.dataset.v }));
    else if (t.id === "btn-demo") show("ctl-out", await post("/api/demo/seed", { n: 40 }));
    else if (t.id === "btn-discover") show("ctl-out", await post("/api/discover"));
    else if (t.id === "btn-consolidate") show("ctl-out", await post("/api/consolidate"));
    else return;
    refresh();
  } catch (err) { $("ctl-out").textContent = "error: " + err.message; }
});

$("decide-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  try {
    const body = {
      user_id: f.get("user_id"), roles: String(f.get("roles")).split(",").map((s) => s.trim()).filter(Boolean),
      action: f.get("action"), resource: f.get("resource"), context: JSON.parse(f.get("context") || "{}"),
      observe: f.get("observe") === "on",
    };
    show("decide-out", await post("/api/decide", body));
    refresh();
  } catch (err) { $("decide-out").textContent = "error: " + err.message; }
});

refresh();
setInterval(refresh, 3000);
