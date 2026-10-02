/*
 * SB Filter — the one "Add / edit filter" dialog.
 *
 * Served by the sb_filter integration at /sb_filter_static/sb-filter-dialog.js.
 * Callers (SB Entity Browser's editor, SB Watch's card and panel) import it on
 * demand and call:
 *
 *   const r = await window.sbFilterDialog.open({ hass, host, entryId?, initial? });
 *   // r = { entry_id, entity_id, name } on save, null on cancel
 *
 * `host` is an element INSIDE Home Assistant's app tree (a card's shadow root,
 * the panel) — the area and label pickers read registries from the app's Lit
 * contexts and fail on document.body. The dialog posts SB Filter's own config /
 * options flow over REST, so validation has one home: the integration.
 */
(() => {
  if (window.sbFilterDialog) return;
  const VERSION = "0.7.0";
  const COMMON_CLASSES = ["battery:%", "temperature", "temperature:°F", "humidity:%", "illuminance:lx", "power:W", "energy:kWh",
    "occupancy", "motion", "door", "window", "moisture", "problem", "connectivity"];
  const ERRORS = { no_name: "Give the filter a name.", name_taken: "Another filter already has this name.",
    empty: "Fill at least one field — a filter that selects nothing is no filter." };
  const LABELS = { name: "Name", patterns: "Patterns", areas: "Areas", labels: "Labels", classes: "Device class · unit" };
  const HELP = {
    patterns: "Words match the entity id or friendly name, any order, case-insensitive; * and ? wildcards. Words in one pattern must all match.",
    areas: "The entity's area, else its device's.", labels: "The entity's own labels or its device's.",
    classes: "class:unit pairs — battery:%, temperature, :°F (either side optional).",
  };
  const STYLE = `
    dialog.sbf { border: none; border-radius: 16px; padding: 0; width: min(560px, calc(100vw - 32px)); max-height: calc(100vh - 48px);
      background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color);
      box-shadow: 0 8px 32px rgba(0,0,0,.35); font-family: var(--ha-font-family-body, Roboto, sans-serif); }
    dialog.sbf::backdrop { background: rgba(0,0,0,.45); }
    dialog.sbf .hd { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px 8px; font-size: 1.2em; font-weight: 500; }
    dialog.sbf .hd button { background: none; border: none; color: var(--secondary-text-color); font-size: 1.2em; cursor: pointer; }
    dialog.sbf .bd { padding: 0 20px; overflow: auto; max-height: calc(100vh - 220px); }
    dialog.sbf .intro { color: var(--secondary-text-color); font-size: .88em; margin: 0 0 8px; }
    dialog.sbf .live { margin: 10px 0 4px; font-size: .9em; }
    dialog.sbf .live b { color: var(--primary-color); }
    dialog.sbf .names { font-size: .82em; color: var(--secondary-text-color); max-height: 120px; overflow: auto; border-top: 1px solid var(--divider-color); padding-top: 6px; }
    dialog.sbf .err { color: var(--error-color, #db4437); font-size: .9em; margin: 8px 0; }
    dialog.sbf .ft { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 20px 16px; }
    dialog.sbf .ft button { font: inherit; border-radius: 18px; padding: 6px 18px; cursor: pointer; border: 1px solid var(--primary-color); }
    dialog.sbf .ft .cancel { background: none; color: var(--primary-color); }
    dialog.sbf .ft .save { background: var(--primary-color); color: var(--text-primary-color, #fff); }
    dialog.sbf .ft .save[disabled] { opacity: .5; cursor: default; }
  `;
  const list = (v) => (Array.isArray(v) ? v : v == null || v === "" ? [] : String(v).split(",")).map((s) => String(s).trim()).filter(Boolean);
  const selectionOf = (d) => { const o = {}; for (const k of ["patterns", "areas", "labels", "classes"]) { const v = list(d[k]); if (v.length) o[k] = v; } return o; };

  async function entityIdFor(hass, entryId) {
    for (let i = 0; i < 20; i++) {
      const r = await hass.connection.sendMessagePromise({ type: "sb_filter/filters" });
      const f = (r.filters || []).find((x) => x.entry_id === entryId);
      if (f && f.entity_id) return f;
      await new Promise((res) => setTimeout(res, 250));
    }
    return null;
  }

  async function submit(hass, entryId, data) {
    const base = entryId ? "config/config_entries/options/flow" : "config/config_entries/flow";
    let flow = await hass.callApi("POST", base, { handler: entryId || "sb_filter" });
    if (!entryId && flow.step_id === "engine") {        // SB Filter's engine is not set up yet: one click first
      await hass.callApi("POST", `${base}/${flow.flow_id}`, {});
      flow = await hass.callApi("POST", base, { handler: "sb_filter" });
    }
    if (flow.type !== "form") throw new Error(flow.reason || "SB Filter refused to start the form");
    const done = await hass.callApi("POST", `${base}/${flow.flow_id}`, data);
    if (done.type === "create_entry") return entryId || done.result?.entry_id;
    try { await hass.callApi("DELETE", `${base}/${flow.flow_id}`); } catch (e) { /* gone */ }
    const msg = Object.values(done.errors || {}).map((k) => ERRORS[k] || k).join(" ") || "Not saved.";
    throw new Error(msg);
  }

  function open({ hass, host, entryId = null, initial = {} }) {
    return new Promise(async (resolve) => {
      await Promise.race([customElements.whenDefined("ha-form"), new Promise((r) => setTimeout(r, 4000))]);
      let data = { name: initial.name || "", patterns: list(initial.patterns), areas: list(initial.areas), labels: list(initial.labels), classes: list(initial.classes) };
      if (entryId) {
        const r = await hass.connection.sendMessagePromise({ type: "sb_filter/filters" });
        const f = (r.filters || []).find((x) => x.entry_id === entryId);
        if (f) data = { name: f.name, patterns: list(f.selection.patterns), areas: list(f.selection.areas), labels: list(f.selection.labels), classes: list(f.selection.classes) };
      }
      const root = host.shadowRoot || host;
      if (!root.querySelector("style[data-sbf]")) { const st = document.createElement("style"); st.dataset.sbf = "1"; st.textContent = STYLE; root.appendChild(st); }
      const d = document.createElement("dialog"); d.className = "sbf";
      d.innerHTML = `<div class="hd"><span>${entryId ? "Edit filter" : "New filter"}</span><button class="x" title="Close">✕</button></div>
        <div class="bd"><p class="intro">${entryId ? "Every rule and card that picks this filter follows the change." : "A named filter selects entities — which ones, never their state. Rules and cards pick it by name."} Every filled field must match; within a field, any entry matches.</p>
          <div class="form"></div><div class="live"></div><div class="names"></div><div class="err" style="display:none"></div></div>
        <div class="ft"><button class="cancel">Cancel</button><button class="save">${entryId ? "Save" : "Create filter"}</button></div>`;
      root.appendChild(d);
      const $ = (q) => d.querySelector(q);
      const form = document.createElement("ha-form");
      form.hass = hass;
      const opts = (vals, extra = []) => [...new Set([...vals, ...extra])].map((v) => ({ value: v, label: v }));
      const schema = () => [
        { name: "name", required: true, selector: { text: {} } },
        { name: "patterns", selector: { select: { multiple: true, custom_value: true, mode: "dropdown", options: opts(data.patterns) } } },
        { name: "areas", selector: { area: { multiple: true } } },
        { name: "labels", selector: { label: { multiple: true } } },
        { name: "classes", selector: { select: { multiple: true, custom_value: true, mode: "dropdown", options: opts(data.classes, COMMON_CLASSES) } } },
      ];
      form.schema = schema();
      form.data = data;
      form.computeLabel = (s) => LABELS[s.name] || s.name;
      form.computeHelper = (s) => HELP[s.name];
      $(".form").appendChild(form);
      let timer = null, seq = 0;
      const live = () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
          const mine = ++seq, sel = selectionOf(data);
          if (!Object.keys(sel).length) { $(".live").textContent = "Nothing selected yet."; $(".names").textContent = ""; return; }
          try {
            const r = await hass.connection.sendMessagePromise({ type: "sb_filter/match", config: sel });
            if (mine !== seq) return;
            const ids = r.ids || [];
            $(".live").innerHTML = `Selects <b>${ids.length}</b> ${ids.length === 1 ? "entity" : "entities"} now`;
            const names = ids.slice(0, 60).map((e) => hass.states[e]?.attributes?.friendly_name || e);
            $(".names").textContent = names.join(" · ") + (ids.length > 60 ? ` · … ${ids.length - 60} more` : "");
          } catch (e) { $(".live").textContent = ""; }
        }, 350);
      };
      form.addEventListener("value-changed", (e) => {
        e.stopPropagation();
        data = { ...data, ...e.detail.value };
        form.data = data;
        $(".err").style.display = "none";
        live();
      });
      const close = (result) => { clearTimeout(timer); try { d.close(); } catch (e) { /* closed */ } d.remove(); resolve(result); };
      $(".x").addEventListener("click", () => close(null));
      $(".cancel").addEventListener("click", () => close(null));
      d.addEventListener("cancel", (e) => { e.preventDefault(); close(null); });
      $(".save").addEventListener("click", async () => {
        const btn = $(".save"); btn.disabled = true;
        try {
          const body = { name: String(data.name || "").trim(), ...{ patterns: [], areas: [], labels: [], classes: [] }, ...selectionOf(data) };
          const id = await submit(hass, entryId, body);
          const f = await entityIdFor(hass, id);
          close({ entry_id: id, entity_id: f?.entity_id || null, name: f?.name || body.name });
        } catch (e) {
          $(".err").style.display = ""; $(".err").textContent = String(e?.message || e?.body?.message || e);
          btn.disabled = false;
        }
      });
      live();
      d.showModal();
    });
  }

  window.sbFilterDialog = { open, version: VERSION };
})();
