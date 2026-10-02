/*
 * SB Filter — the sidebar page (/sb-filter, admins).
 *
 * Every named filter: its live count, what it selects, and WHAT USES IT — SB Watch
 * rules (reported by SB Watch through sb_filter/usage) and dashboard cards (found
 * here by reading every dashboard, Param Card templates like
 * sensor.demo_fp300_$value$_filter included). New / Edit open the one filter dialog
 * (sb-filter-dialog.js); Delete says what will lose its filter before it deletes.
 * Deep links: /sb-filter?edit=<entry_id>, ?add=1 (the integration's own forms link here).
 */
const PANEL_VERSION = "0.8.0";
const pesc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const selSummary = (sel) => Object.entries(sel || {}).map(([k, v]) => `<span class="k">${pesc(k)}</span> ${(Array.isArray(v) ? v : [v]).map((x) => `<code>${pesc(x)}</code>`).join(" ")}`).join(" · ");

// A Param Card's parameters and their choice values: {name: [values]}; a parameter whose
// choices live elsewhere (a silent socket, an areas/labels source) is left out.
const paramChoices = (pc) => {
  const out = {};
  const add = (name, choices) => { if (name && Array.isArray(choices) && choices.length) out[name] = choices.map((c) => (typeof c === "object" ? c.value : c)).map((x) => String(x ?? "")); };
  if (pc.parameter) add(pc.parameter, pc.choices);                       // the older single-parameter form
  (pc.parameters || []).forEach((p) => add(p.name, p.choices));
  return out;
};
const slug = (x) => String(x).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
// every concrete value of a template, or null when a parameter's choices are unknown here
const expand = (tpl, params) => {
  let outs = [""], rest = tpl, m;
  const rx = /\$([a-zA-Z_][\w-]*)(?::(\w+))?\$/;
  while ((m = rest.match(rx))) {
    const vals = params[m[1]];
    if (!vals) return null;
    const pre = rest.slice(0, m.index);
    outs = outs.flatMap((o) => vals.map((v) => o + pre + (m[2] === "slug" ? slug(v) : v)));
    rest = rest.slice(m.index + m[0].length);
  }
  return outs.map((o) => o + rest);
};
// choices unknown: the template's fixed parts, any value between
const templateRe = (tpl) => new RegExp("^" + tpl.split(/\$[^$]+\$/).map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("[a-z0-9_]+") + "$");

class SbFilterPanel extends HTMLElement {
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (!this.shadowRoot) this._build();
    if (this._menu) this._menu.hass = hass;
    if (first) { this._load().then(() => this._deepLink()); this._ready = this._loadDialog().catch(() => {}); }
    else this._liveCounts();
  }
  set narrow(v) { this._narrow = v; if (this._menu) this._menu.narrow = v; }
  set route(_v) { /* single page */ }
  set panel(_v) { /* no panel config */ }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>
      :host { display: block; min-height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color); font-family: var(--ha-font-family-body, Roboto, sans-serif); }
      .bar { display: flex; align-items: center; gap: 4px; height: var(--header-height, 56px); padding: 0 12px; box-sizing: border-box; position: sticky; top: 0; z-index: 2;
             background: var(--app-header-background-color, var(--primary-color)); color: var(--app-header-text-color, #fff); border-bottom: 1px solid var(--divider-color); }
      .title { font-size: 20px; flex: 1; margin-left: 4px; }
      .bar a { color: inherit; font-size: 14px; opacity: .85; text-decoration: none; padding: 6px 10px; border-radius: 14px; }
      .bar a:hover { background: rgba(127,127,127,.2); opacity: 1; }
      .page { padding: 16px; }
      .col { max-width: 900px; margin: 0 auto; }
      .intro { color: var(--secondary-text-color); font-size: 14px; margin: 0 4px 12px; line-height: 1.5; }
      .tools { display: flex; gap: 10px; align-items: center; margin: 0 0 10px; flex-wrap: wrap; }
      .tools input { flex: 1 1 200px; font: inherit; padding: 8px 12px; border-radius: 18px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
      .new { font: inherit; border: none; border-radius: 18px; padding: 8px 16px; cursor: pointer; background: var(--primary-color); color: var(--text-primary-color, #fff); display: inline-flex; align-items: center; gap: 6px; }
      .new ha-icon { --mdc-icon-size: 18px; }
      ha-card { padding: 4px 16px; }
      .row { border-top: 1px solid var(--divider-color); padding: 10px 0; }
      .row:first-child { border-top: none; }
      .head { display: flex; align-items: center; gap: 12px; }
      .main { flex: 1; min-width: 0; cursor: pointer; }
      .name { font-weight: 500; }
      .eid { color: var(--secondary-text-color); font-size: .8em; margin-left: 6px; font-weight: normal; }
      .sel { color: var(--secondary-text-color); font-size: .85em; margin-top: 2px; overflow-wrap: anywhere; }
      .sel .k { opacity: .75; }
      .sel code, .det code { font-size: .95em; background: rgba(127,127,127,.12); padding: 0 4px; border-radius: 4px; }
      .used { font-size: .85em; margin-top: 3px; }
      .used.none { color: var(--secondary-text-color); font-style: italic; }
      .count { font-size: .9em; padding: 3px 10px; border-radius: 12px; background: rgba(var(--rgb-primary-color, 3,169,244), .14); color: var(--primary-color); min-width: 2em; text-align: center; }
      .btn { cursor: pointer; color: var(--secondary-text-color); --mdc-icon-size: 22px; }
      .btn.del:hover { color: var(--error-color); }
      .det { margin: 8px 0 2px; font-size: .88em; display: grid; gap: 8px; }
      .det h4 { margin: 0 0 4px; font-size: .9em; color: var(--secondary-text-color); font-weight: 500; }
      .det ul { margin: 0; padding-left: 18px; }
      .det a { color: var(--primary-color); }
      .names { color: var(--secondary-text-color); line-height: 1.5; max-height: 160px; overflow: auto; }
      .empty, .msg { color: var(--secondary-text-color); font-style: italic; padding: 14px 0; }
      .msg.err { color: var(--error-color); font-style: normal; }
      .ver { color: var(--secondary-text-color); font-size: 12px; margin: 12px 4px 0; }
      dialog.del { border: none; border-radius: 16px; padding: 0; width: min(520px, calc(100vw - 32px)); background: var(--card-background-color); color: var(--primary-text-color); box-shadow: 0 8px 32px rgba(0,0,0,.35); }
      dialog.del::backdrop { background: rgba(0,0,0,.45); }
      dialog.del .bd { padding: 18px 20px 4px; line-height: 1.5; }
      dialog.del .bd h3 { margin: 0 0 8px; font-weight: 500; }
      dialog.del .warn { color: var(--warning-color, #ff9800); }
      dialog.del .ft { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 20px 16px; }
      dialog.del button { font: inherit; border-radius: 18px; padding: 6px 18px; cursor: pointer; border: 1px solid var(--primary-color); background: none; color: var(--primary-color); }
      dialog.del .go { background: var(--error-color, #db4437); border-color: var(--error-color, #db4437); color: #fff; }
    </style>
    <div class="bar"><ha-menu-button></ha-menu-button><div class="title">SB Filter</div><a href="/config/integrations/integration/sb_filter">Integration page</a></div>
    <div class="page"><div class="col">
      <div class="intro">A named filter selects entities — which ones, never what state they are in. SB Watch rules and SB Entity Browser cards pick a filter by name, so editing one here changes every rule and card that uses it. Click a filter to see what it selects and what uses it.</div>
      <div class="tools"><input class="q" type="search" placeholder="Search filters"><button class="new"><ha-icon icon="mdi:plus"></ha-icon>New filter</button></div>
      <ha-card><div class="list"><div class="msg">Loading…</div></div></ha-card>
      <div class="ver">SB Filter ${PANEL_VERSION}</div>
    </div></div>`;
    this._menu = root.querySelector("ha-menu-button");
    this._menu.narrow = this._narrow;
    this._open = new Set();
    root.querySelector(".new").addEventListener("click", () => this._dialog(null));
    root.querySelector(".q").addEventListener("input", () => this._render());
  }

  // ---- data ------------------------------------------------------------------------
  async _load() {
    const h = this._hass;
    try {
      const [f, u, cards] = await Promise.all([
        h.connection.sendMessagePromise({ type: "sb_filter/filters" }),
        h.connection.sendMessagePromise({ type: "sb_filter/usage" }).catch(() => ({ usage: {} })),
        this._scanDashboards(),
      ]);
      this._filters = f.filters || [];
      this._usage = u.usage || {};
      this._cards = cards;
      this._error = null;
    } catch (e) {
      this._error = String(e?.message || e);
    }
    this._render();
  }

  // Every SB Entity Browser on every dashboard that names a filter: {ref, re, where, url}.
  async _scanDashboards() {
    const h = this._hass, out = [];
    let dashes = [];
    try { dashes = await h.connection.sendMessagePromise({ type: "lovelace/dashboards/list" }); } catch (e) { /* none */ }
    const all = [{ url_path: null, title: "Overview" }, ...dashes];
    await Promise.all(all.map(async (d) => {
      let cfg;
      try { cfg = await h.connection.sendMessagePromise(d.url_path ? { type: "lovelace/config", url_path: d.url_path } : { type: "lovelace/config" }); } catch (e) { return; }
      (cfg.views || []).forEach((v, vi) => {
        const walk = (o, params) => {
          if (Array.isArray(o)) { o.forEach((x) => walk(x, params)); return; }
          if (!o || typeof o !== "object") return;
          if (o.type === "custom:sb-param-card") params = { ...params, ...paramChoices(o) };
          if (o.type === "custom:sb-entity-browser" && typeof o.filter === "string" && o.filter) {
            const tpl = /\$[^$]+\$/.test(o.filter);
            out.push({
              ref: o.filter,
              refs: tpl ? expand(o.filter, params) : [o.filter],     // a Param Card template: every entity id its choices can make
              where: `${d.title || d.url_path} › ${v.title || v.path || `view ${vi + 1}`} › ${o.title || "untitled card"}${tpl ? " (Param Card choice)" : ""}`,
              url: `/${d.url_path || "lovelace"}/${v.path || vi}`,
            });
          }
          Object.values(o).forEach((x) => walk(x, params));
        };
        walk(v, {});
      });
    }));
    return out;
  }

  _usersOf(f) {
    const rules = (this._usage[f.entry_id] || []);
    const cards = (this._cards || []).filter((c) => (c.refs ? c.refs.includes(f.entity_id) : templateRe(c.ref).test(f.entity_id || "")));
    return { rules, cards };
  }

  // ---- render ------------------------------------------------------------------------
  _render() {
    const root = this.shadowRoot, list = root.querySelector(".list"), h = this._hass;
    if (this._error) { list.innerHTML = `<div class="msg err">${pesc(this._error)}</div>`; return; }
    if (!this._filters) return;
    const q = root.querySelector(".q").value.trim().toLowerCase();
    const shown = this._filters.filter((f) => !q || f.name.toLowerCase().includes(q) || JSON.stringify(f.selection).toLowerCase().includes(q));
    if (!shown.length) { list.innerHTML = `<div class="empty">${this._filters.length ? "No filter matches the search." : "No filters yet — New filter makes one."}</div>`; return; }
    list.innerHTML = shown.map((f) => {
      const { rules, cards } = this._usersOf(f);
      const n = rules.length + cards.length;
      const usedTxt = n ? [rules.length ? `${rules.length} rule${rules.length === 1 ? "" : "s"}` : "", cards.length ? `${cards.length} card${cards.length === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ") : "not used yet";
      const open = this._open.has(f.entry_id);
      let det = "";
      if (open) {
        const ids = h.states[f.entity_id]?.attributes?.entity_ids || [];
        const names = ids.slice(0, 200).map((e) => pesc(h.states[e]?.attributes?.friendly_name || e)).join(" · ") + (ids.length > 200 ? ` · … ${ids.length - 200} more` : "");
        det = `<div class="det">
          <div><h4>Used by</h4>${n ? `<ul>${rules.map((r) => `<li>${pesc(r.kind || "Rule")}: ${r.url ? `<a href="${pesc(r.url)}">${pesc(r.name)}</a>` : pesc(r.name)}</li>`).join("")}${cards.map((c) => `<li>Card: <a href="${pesc(c.url)}">${pesc(c.where)}</a></li>`).join("")}</ul>` : `<span class="used none">nothing yet</span>`}</div>
          <div><h4>Selects now (${ids.length})</h4><div class="names">${names || "nothing"}</div></div>
          <div><h4>Sensor</h4><code>${pesc(f.entity_id || "—")}</code></div>
        </div>`;
      }
      return `<div class="row" data-id="${pesc(f.entry_id)}">
        <div class="head">
          <div class="main"><div class="name">${pesc(f.name)}</div><div class="sel">${selSummary(f.selection)}</div><div class="used ${n ? "" : "none"}">${usedTxt}</div></div>
          <span class="count" data-e="${pesc(f.entity_id || "")}">${pesc(h.states[f.entity_id]?.state ?? f.count ?? "…")}</span>
          <ha-icon class="btn edit" icon="mdi:pencil-outline" title="Edit"></ha-icon>
          <ha-icon class="btn del" icon="mdi:delete-outline" title="Delete"></ha-icon>
        </div>${det}</div>`;
    }).join("");
    list.querySelectorAll(".row").forEach((row) => {
      const f = this._filters.find((x) => x.entry_id === row.dataset.id);
      row.querySelector(".main").addEventListener("click", () => { this._open.has(f.entry_id) ? this._open.delete(f.entry_id) : this._open.add(f.entry_id); this._render(); });
      row.querySelector(".edit").addEventListener("click", () => this._dialog(f.entry_id));
      row.querySelector(".del").addEventListener("click", () => this._confirmDelete(f));
    });
  }

  _liveCounts() {
    this.shadowRoot?.querySelectorAll(".count[data-e]").forEach((el) => {
      const st = this._hass.states[el.dataset.e];
      if (st && el.textContent !== st.state) el.textContent = st.state;
    });
  }

  // ---- actions -----------------------------------------------------------------------
  async _loadDialog() {
    if (!window.sbFilterDialog) {
      const info = await this._hass.connection.sendMessagePromise({ type: "sb_filter/info" });
      await import(info.dialog_url);
    }
    await window.sbFilterDialog.loadHaForm?.();           // HA's form controls, before anyone clicks
  }

  async _dialog(entryId) {
    const btn = this.shadowRoot.querySelector(".new");
    btn.disabled = true; const label = btn.innerHTML; btn.textContent = "Opening…";
    try {
      await this._loadDialog();
      btn.disabled = false; btn.innerHTML = label;
      const res = await window.sbFilterDialog.open({ hass: this._hass, host: this, entryId });
      if (res) { this._open.add(res.entry_id); await this._load(); }
    } catch (e) {
      btn.disabled = false; btn.innerHTML = label;
      this.shadowRoot.querySelector(".list").insertAdjacentHTML("afterbegin", `<div class="msg err">${pesc(e?.message || e)}</div>`);
    }
  }

  _confirmDelete(f) {
    const { rules, cards } = this._usersOf(f);
    const d = document.createElement("dialog"); d.className = "del";
    const users = [...rules.map((r) => `${pesc(r.kind || "Rule")} “${pesc(r.name)}”`), ...cards.map((c) => `Card: ${pesc(c.where)}`)];
    d.innerHTML = `<div class="bd"><h3>Delete “${pesc(f.name)}”?</h3>${users.length
      ? `<div class="warn">Still used by ${users.length}:</div><ul>${users.map((u) => `<li>${u}</li>`).join("")}</ul><div>They will select nothing (“filter not found”) until they are pointed at another filter.</div>`
      : "<div>Nothing uses it.</div>"}</div>
      <div class="ft"><button class="no">Cancel</button><button class="go">Delete</button></div>`;
    this.shadowRoot.appendChild(d);
    const close = () => { try { d.close(); } catch (e) { /* closed */ } d.remove(); };
    d.querySelector(".no").addEventListener("click", close);
    d.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
    d.querySelector(".go").addEventListener("click", async () => {
      d.querySelector(".go").disabled = true;
      try { await this._hass.callApi("DELETE", `config/config_entries/entry/${f.entry_id}`); }
      catch (e) { d.querySelector(".bd").insertAdjacentHTML("beforeend", `<div class="warn">${pesc(e?.message || e)}</div>`); d.querySelector(".go").disabled = false; return; }
      close(); this._open.delete(f.entry_id); await this._load();
    });
    d.showModal();
  }

  async _deepLink() {
    const q = new URLSearchParams(location.search);
    const edit = q.get("edit"), add = q.get("add");
    if (!edit && !add) return;
    history.replaceState(history.state, "", location.pathname);
    if (edit) this._open.add(edit);
    this._render();
    this._dialog(add ? null : edit);
  }
}
if (!customElements.get("sb-filter-panel")) customElements.define("sb-filter-panel", SbFilterPanel);
console.info("%c SB-FILTER-PANEL %c v" + PANEL_VERSION + " ", "background:#455a64;color:#fff", "background:#90a4ae;color:#000");
