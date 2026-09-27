# SB Filter

The one implementation of the **SB entity-filter grammar** for Home Assistant — a
small integration with no entities of its own. It is what an
[SB Entity Browser](https://github.com/snadboy/sb-entity-browser) card asks
"which entities match this config?", and what SB Watch rules are built on.

```yaml
patterns: [fp300]           # words in a pattern AND; patterns OR
labels: [matter_hub]        # the entity's own labels or its device's
areas: [kitchen]
device_classes: [battery]
units: ["%"]
states: [unavailable, "<20", "40-60"]   # values or ranges, ORed
state_for: 2h               # in the current state for at least…
```

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

State changes and registry edits coalesce into one recompute per second; a
`state_for` term is re-evaluated every 30 s. Nothing configured matches nothing.

## Python

```python
from custom_components.sb_filter.ha import match_now
flt, result = match_now(hass, {"labels": ["matter_hub"], "states": ["off"]})
result.ids
```
