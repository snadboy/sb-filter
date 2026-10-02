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

## Install

HACS → custom repository `snadboy/sb-filter` (Integration), then
*Settings → Devices & services → Add integration → SB Filter*. One click; nothing
to configure. Integrations that depend on it list `sb_filter` in their manifest.

## WebSocket API

| Command | Payload | Result |
|---|---|---|
| `sb_filter/match` | `config` | `{ids, pattern_counts, configured, unreadable, grammar}` |
| `sb_filter/subscribe` | `config` | the same payload as an event, first immediately and then whenever `ids` change |
| `sb_filter/info` | — | `{grammar}` |

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
