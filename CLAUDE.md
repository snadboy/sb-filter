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
