# SB Filter

The one implementation of the **SB entity-filter grammar** for Home Assistant: it
answers **which entities** — never what state they are in. A small integration
whose only entity, `sensor.sb_filter_live_filters`, lists every filter currently
being watched (by which card or rule, matching how many, when it last changed).
It is what an [SB Entity Browser](https://github.com/snadboy/sb-entity-browser)
card asks "which entities does this config select?", and the selection half of
every [SB Watch](https://github.com/snadboy/sb-watch) rule.

Three pieces, one job each:

| Piece | Job |
|---|---|
| **SB Filter** (this) | which entities: patterns, labels, areas, device class, unit |
| **SB Watch** | their state — values, ranges, time in state, rates — and what to do about it |
| **SB Entity Browser** | show a list: SB Filter's selection, *or* an SB Watch rule's active set |

```yaml
patterns: [fp300]           # words in a pattern AND; patterns OR
labels: [matter_hub]        # the entity's own labels or its device's
areas: [kitchen]
device_classes: [battery]
units: ["%"]
classes: ["battery:%"]      # device class AND unit as pairs
```

Grammar 5 dropped `states`, `state_min`, `state_max`, `state_for`, `rate` and
`rate_window` — they moved to SB Watch. A config that still carries one selects
nothing and names it in `unreadable`.

The full grammar is in [FILTER.md](FILTER.md); `tests/vectors.json` is its
executable specification (`python3 tests/test_vectors.py`, no HA needed).

## Named filters — the one place selections are made

A named filter is a selection with a name: patterns, areas, labels, device
class · unit pairs. Each is its own entry of this integration, with a device and
one sensor — `sensor.<name>_filter`, state = how many entities it selects, the
ids in `entity_ids` (not recorded; the count is). SB Watch rules and SB Entity
Browser cards **pick** a filter (or list individual entities) instead of writing
their own selection, so editing a filter updates every rule and card that uses it.

Make or edit one:
- **the shared dialog** — *New filter…* / *Edit filter…* buttons in the SB Watch
  panel, the SB Watch Card's editor and the SB Entity Browser's editor all open
  the same dialog (`frontend/sb-filter-dialog.js`, served by this integration),
  with a live count and the matching names;
- **Settings → Devices & services → SB Filter → Add entry** (or the gear on a
  filter) — the same fields in Home Assistant's own form.

Both post the same config/options flow, so validation lives in one place: a
name (unique), and at least one field. SB Filter's own sensors are never
selected by any filter.

## Install

HACS → custom repository `snadboy/sb-filter` (Integration), then
*Settings → Devices & services → Add integration → SB Filter*. The first entry is
the engine (one click, nothing to configure); every entry after it is a named
filter. Integrations that depend on it list `sb_filter` in their manifest.

## WebSocket API

| Command | Payload | Result |
|---|---|---|
| `sb_filter/match` | `config` | `{ids, pattern_counts, configured, unreadable, grammar}` |
| `sb_filter/subscribe` | `config` | the same payload as an event, first immediately and then whenever `ids` change |
| `sb_filter/filters` | — | every named filter: `{entry_id, name, entity_id, selection, count}` |
| `sb_filter/info` | — | `{grammar, version, dialog_url}` — `dialog_url` is the shared filter dialog |

A selection recomputes on registry edits and on state changes that add or remove
an entity or change its name, device class or unit — never on a state value
alone. Bursts coalesce into one recompute per second. Nothing configured matches
nothing.

## Python

```python
from custom_components.sb_filter.ha import match_now
flt, result = match_now(hass, {"labels": ["matter_hub"]})
result.ids
```
