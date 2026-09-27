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
