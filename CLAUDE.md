# SB Filter — session notes

Repo `snadboy/sb-filter`, local `~/projects/git/sb-filter`, branch `main`, MIT.
Born 2026-09-27 as step 2 of the SB Watch plan (memory `project_sb_watch`):
the single implementation of the filter grammar that SB Entity Browser and
SB Watch both use. Domain `sb_filter`, integration_type service, no entities,
single-instance one-click config flow; WS commands are registered in
`async_setup` so a dependent integration pulls them in even without the entry.

## Layout

- `custom_components/sb_filter/grammar.py` — parsing only, pure Python
  (`parse_filter`, `parse_pattern`, `parse_range`, `parse_duration`, `as_list`).
- `matcher.py` — `evaluate(Filter, Snapshot, now)`, pure; Snapshot = plain
  rows (states, entity registry, device registry, `formatted(id)` callback).
- `ha.py` — `build_snapshot(hass)` (translations via
  `homeassistant.helpers.translation.async_translate_state`, cached),
  `match_now`, `FilterSubscription` (state_changed + 4 registry events +
  30 s tick when `state_for`; 1 s debounce; sends only when ids change).
- `websocket.py` — `sb_filter/match`, `sb_filter/subscribe`, `sb_filter/info`.
- `FILTER.md` — the grammar (version in `const.GRAMMAR_VERSION`).
- `tests/vectors.json` + `tests/test_vectors.py` — 38 vectors, plain
  `python3` (a stub package loads the pure modules past the HA-importing
  `__init__`).

## Grammar decisions worth remembering

- Formatted state = HA's translated state for NON-numeric states; numeric
  states format as themselves (the card's frontend `formatEntityState` added
  units — dropped on purpose, no one matches "88.2 °F").
- `sensor.` matches `binary_sensor.` too (implied wildcards) — documented,
  vector'd, not "fixed".
- Nothing configured = nothing matched. Never the whole estate.
- `state_for` from `last_changed`, bare number = minutes, default `>=`.

## Deploying to HA (no HACS yet)

```bash
tar czf /tmp/sbf.tgz -C custom_components sb_filter
ssh snadboy@homeassistant "cat > /tmp/sbf.tgz" < /tmp/sbf.tgz
ssh snadboy@homeassistant "cd /config/custom_components && tar xzf /tmp/sbf.tgz && rm /tmp/sbf.tgz"
```
Then a FULL restart (a config-entry reload does not re-import Python).

## 0.1.1 → 0.1.2 (2026-09-27) — registry iteration, and an outage I caused

HA 2026.9 reports mapping-style use of `DeviceRegistry.devices` (`.values()`,
`[]`, `.get()`; removed 2027.9). The `devices` property is a deprecation
VIEW whose ITERATION yields `DeviceEntry` values — `for d in dev_reg.devices`
is the supported form. `EntityRegistry.entities` is NOT a view: it is a
plain `UserDict`, iteration yields KEYS, `.values()` stays.

0.1.1 changed both to iteration → `e.entity_id` on a str → every
`build_snapshot` raised → every card and every rule dead for ~4 min (160
tracebacks) until the revert. 0.1.2 = devices iterate, entities `.values()`.
Verified: no deprecation line after restart, `labels: [matter_hub]` → 6.
Lesson: read the deprecation's SOURCE (the docstring says exactly which
form is supported) before changing two containers on one warning.

## 0.2.0 — grammar v2 (2026-09-28)

User-driven revisit of `states`: THREE KINDS, decided by the state itself.
Numeric → ranges + **equality** (a plain number entry; `100` matches
`100.0`); never string-compared. Binary/string → raw always, HA's
translated alias per entity (device_class or translation_key). A word never
matches a numeric state and vice versa. Typos: **validation by
membership** — `unmatched_values` = words in NO selected entity's
vocabulary, with did-you-mean (difflib ≥0.75, one suggestion per
underlying state, translated spelling first). Vocabulary comes from HA's
own translation cache (`async_get_cached_translations`, keys
`component.<domain>.entity_component.<dc|_>.state.*` or
`component.<platform>.entity.<domain>.<tkey>.state.*`) + enum `options` +
the current raw state — no hand table, no type annotation asked of the
user (`device_classes` is the qualifier when wanted). New WS
`sb_filter/values` {config} → vocabulary of the non-state selection with
`current`/`possible` counts, for chips. 49 vectors (`vocabulary` map in the
snapshot). Numeric equality was the one v1→v2 meaning change.

## 0.3.0 — grammar v3: `rate` (2026-09-28)

`rate: [">0.5/h", "<-2/h"]` (+ optional `rate_window`): change of a numeric
state per m/h/d; reference = latest sample AT OR BEFORE now−window, none →
unknown → never matches (a 15-min-old sensor has no hourly rate; and with
the default 1-minute window a `/m` term is "the last minute", which is 0
when nothing changed — vector'd). `RateTracker` in `hass.data`: per-entity
deques seeded ONCE from the recorder (`history.state_changes_during_period`
per entity inside one executor job, chunks of 50) then appended from
state_changed; trimmed to 2×window+60 s keeping one older reference
sample. `_scope_ids` = the non-rate categories' selection, numeric only;
a rate alone = every numeric entity (expensive — documented).
`async_match` (WS match is now `async_response`) and the subscription's
`_seed_then_recompute` await seeding; rate subscriptions tick every 60 s
and re-seed newly-scoped entities after each recompute. `after_dependencies:
["recorder"]`. 61 vectors (`history` map in the snapshot).

## 0.4.0 — `sensor.sb_filter_live_filters` (2026-09-28)

User: "an entity that will show a list of the current filters". First (and
only) entity: state = number of live subscriptions; attributes `filters[]`
(id, origin, config, matched, configured, unreadable, terms, started,
last_change, recomputes, pushes), `rules`/`cards` counts, `rate_buffers`,
cache sizes, `grammar`. Every `FilterSubscription` registers in
`hass.data[DOMAIN]["subs"]` on start and drops on stop; a dispatcher
signal (`SIGNAL_SUBS`) refreshes the sensor on start/stop/push. Origins:
WS `subscribe` takes an optional `origin` and appends the connection's
user name ("card: Lights on · Dan"); sb_watch passes "rule: <name>".
SERVICE device "SB Filter"; sensor platform via the config entry.

## 0.4.1 — rate buffers released when the last rate filter stops (2026-09-28)

User asked about aging/removal. Subscriptions need none: card entries die
with their WebSocket connection (verified: raw socket subscribe → close →
gone), rule entries with the config entry; HA's ping/pong reaps dead
connections. The one accumulation was `RateTracker` buffers (entity set
never shrank). Now `release_all()` when the last rate-bearing subscription
stops; the next rate filter re-seeds from the recorder.

## 0.5.0 — grammar 4: `classes` pairs (2026-10-01)

`classes: ["battery:%", "temperature", ":°F"]` (or `{device_class, unit}`): an
entity passes when ANY entry matches, an entry = class (case-insensitive, if
given) AND unit (exact, if given). Its own category, ANDed with the rest —
including `device_classes`/`units`, which stay. Why: two independent lists
admit battery-in-°F; SB Watch's rule form (0.9.0) writes pairs. 8 new vectors
(69 total); `values()` and the rate scope carry `classes` too.

## 0.6.0 — grammar 5: selection only (2026-10-02)

User decision ("focused purpose"): **SB Filter = which entities, never their
state.** SB Watch owns every state question and the actions; the Entity Browser
shows SB Filter's selection OR an SB Watch rule (`rule:`), never both.
- Removed: `states`/`state_min`/`state_max`/`state_for`/`rate`/`rate_window`,
  `unmatched_values`, vocabularies/translations, `RateTracker`, `sb_filter/values`,
  the 30 s / 60 s ticks, the recorder after-dependency. A pattern token no longer
  matches a state exactly (ids + names only).
- A config still carrying a state key selects NOTHING, stays `configured`, and
  lists each key in `unreadable` — old clients get an empty list, not a silently
  widened one.
- `FilterSubscription` listens to state_changed with an `event_filter`
  (`selection_moved`: entity added/removed, or friendly_name / device_class /
  unit changed — HA passes the event DATA to the filter) + the 4 registry events.
- The state vectors were PORTED to sb-watch first (`tools/port_vectors.py` there,
  run against grammar 4: 42/42 reproduced) — then removed here. 28 vectors now.
- Live check after the switch: every rule's selection count identical
  (66/6/76/11/1×5), `binary_sensor.` = 283 = an independent tally of the states.

## 0.7.0 — named filters (2026-10-02)

User: "do we want multiple paths creating filters?" → no. **Named filters, made in
ONE place (SB Filter); rules and cards pick a filter (or create one via a button
that opens the add-filter dialog) or individual entities.**
- Entries: the ENGINE (unique_id `sb_filter`, data {}) + one entry per NAMED
  FILTER (data `{"kind": "filter"}`, options {name, patterns, areas, labels,
  classes}). `single_config_entry` dropped; the user step creates the engine when
  none exists, else a filter; `async_step_import` (SB Watch's migration);
  options flow edits a filter; `async_supports_options_flow` hides Configure on the
  engine. Validation: name required + unique (case-insensitive), selection configured.
- `named.py`: `NamedFilter` (a FilterSubscription, origin "filter: <name>"),
  `async_listen(hass, entry_id, cb)` — the listener registry OUTLIVES the entry, so
  an edit (= reload) hands followers the new ids with no gap; nothing is sent on
  unload, `missing` only on removal (`async_remove_entry`). `async_find_or_create`
  (dedupe by exact selection, unique name by suffix).
- `sensor.<name>_filter` (`FilterSensor`): state = count, `entity_ids`
  (`_unrecorded_attributes`), `selection`, `filter_id`.
- WS `sb_filter/filters`; `sb_filter/info` → `dialog_url`.
- `frontend/sb-filter-dialog.js` (static `/sb_filter_static`): THE add/edit dialog
  — `window.sbFilterDialog.open({hass, host, entryId?, initial?})` → {entry_id,
  entity_id, name} | null. ha-form fields, live count + names via `sb_filter/match`,
  posts the config/options flow over REST. `host` must be inside HA's app tree.
- **Self-reference bug found live:** "Occupancy sensors Filter" matched its own
  pattern "Occupancy sensor" (17 → 18). `build_snapshot` now skips every entity of
  platform `sb_filter`. Verified 17 / 25 after the restart.

## 0.7.1 — an edit updates the filter IN PLACE (2026-10-02)

User asked whether three cards on one filter see an edit at once. Measured: yes,
0.08 s — but the entry RELOAD blanked the sensor (unavailable, 0 ids) on the way.
Now the update listener calls `NamedFilter.update(entry)` (new FilterSubscription
started, old stopped, device renamed via the device registry); measured 15 → 16 →
15 with no unavailable step.
