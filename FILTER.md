# SB filter grammar — version 1

One filter selects entities. It is the config of an SB Entity Browser card and the
target of an SB Watch rule; `sb_filter` is its only implementation.

```yaml
patterns: [fp300 $q$, "light."]     # OR between patterns; words within one pattern AND
labels: [matter_hub]                 # entity's own labels OR its device's
areas: [kitchen]                     # entity's area, else its device's
device_classes: [battery]            # attribute device_class, case-insensitive
units: ["%"]                         # attribute unit_of_measurement, exact
states: [on, Detected, unavailable, "<20", ">=80", "40-60"]   # values OR ranges
state_min: 20                        # shorthand for one more inclusive range
state_max: 50
state_for: 2h                        # time in the current state
```

**Across categories: AND.** Every category that is configured must be satisfied.
An empty category does not constrain. **Within a category: OR.**

**Nothing configured matches nothing** — never the whole estate.

## patterns

A pattern is whitespace-separated tokens; **all tokens must match** (AND). A token
matches when, case-insensitively:

- it is found **anywhere** in the entity id (wildcards implied on both ends), or
- anywhere in the friendly name, or
- with no wildcard in it, it **equals** the raw state or the formatted state exactly
  (so `CR2450` finds the battery-type sensors reporting CR2450).

`*` = any run, `?` = one character. A blank pattern is ignored (it never excludes
anything and never counts). Each pattern reports how many entities it matched
(`pattern_counts`, index-aligned with the list).

## labels, areas

Lists of ids. An entity carries a label itself **or through its device** — HA
does not propagate device labels. An entity is in its own area, else its device's.
HA picker placeholders (`___no_items_available___`) are dropped.

## device_classes, units

Lists (or comma strings). Device class compares case-insensitively; unit exactly.
They pin a numeric range to the right quantity: `sensor.*battery` with `<20`
otherwise sweeps in battery *voltage* sensors at 2.98 V.

## states

A list or comma string. Each entry is a **value** or a **range expression**:

| Entry | Meaning |
|---|---|
| `on`, `Detected`, `unavailable` | equals the raw **or the formatted** state, case-insensitive |
| `<20` `<=20` `>80` `>=80` | numeric comparison |
| `20-50` `20..50` | inclusive span, either way round |

An entity passes with a matching value **or** a number inside any range. Only a
numeric state can satisfy a range. `unavailable` / `unknown` are ordinary values.

**Formatted state** is HA's translated state for non-numeric states (`Clear`,
`Below horizon`); a numeric state formats as itself (no unit).

## state_for

Time in the **current** state, measured from `last_changed` (a state change; an
attribute-only update does not reset it) with Home Assistant's clock.

| Entry | Meaning |
|---|---|
| `2h`, `>=2h` | at least this long (default comparator is `>=`) |
| `>2h` | strictly longer |
| `<5m`, `<=5m` | changed within the last five minutes |
| `1h30m`, `90s`, `1d` | units d h m s combine |
| `120` | a bare number is **minutes** |

An unreadable value is ignored and reported in `unreadable`.

## Results

`ids` (sorted), `pattern_counts`, `configured`, `unreadable`, `grammar` (this
document's version). A subscription re-sends only when `ids` change; state and
registry changes coalesce into one recompute per second, and a `state_for` term
is re-evaluated every 30 s.
