# SB filter grammar — version 3

One filter selects entities. It is the config of an SB Entity Browser card and the
target of an SB Watch rule; `sb_filter` is its only implementation.

```yaml
patterns: [fp300 $q$, "light."]     # OR between patterns; words within one pattern AND
labels: [matter_hub]                 # entity's own labels OR its device's
areas: [kitchen]                     # entity's area, else its device's
device_classes: [battery]            # attribute device_class, case-insensitive
units: ["%"]                         # attribute unit_of_measurement, exact
states: [on, Detected, unavailable, 100, "<20", ">=80", "40-60"]   # see "states"
state_min: 20                        # shorthand for one more inclusive range
state_max: 50
state_for: 2h                        # time in the current state
rate: [">0.5/h", "<-2/h"]           # change per minute/hour/day, ORed
rate_window: 1h                      # optional; default = the largest unit among the rate terms
```

**Across categories: AND.** Every category that is configured must be satisfied.
An empty category does not constrain. **Within a category: OR.**

**Nothing configured matches nothing** — never the whole estate.

## patterns

A pattern is whitespace-separated tokens; **all tokens must match** (AND). A token
matches when, case-insensitively:

- it is found **anywhere** in the entity id (wildcards implied on both ends), or
- anywhere in the friendly name, or
- with no wildcard in it, it **equals** the raw state or the translated state exactly
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
otherwise sweeps in battery *voltage* sensors at 2.98 V. They are also the way to
pin a translated value to one meaning (`Clear` as occupancy, not weather).

## states — three kinds of state

A list or comma string. **An entity's state is one of three kinds**, decided by the
state itself, and each kind is compared its own way. An entity passes when any
entry matches; the OR is across the whole list.

### Numeric

A state that parses as a number (`72.5`, `100`, `-3`) is compared **only
numerically** — never as a string, never with a unit (that is what `units` is for).

| Entry | Meaning |
|---|---|
| `100`, `20.5`, `-3` | **equality**: `100` matches `100` and `100.0` |
| `<20` `<=20` `>80` `>=80` | comparison |
| `20-50` `20..50` | inclusive span, either way round |

`NaN`/`inf` are not numeric states. `state_min`/`state_max` add one more span.

### Binary

`on` / `off` always match the raw state, case-insensitively. The **translated
pair for the entity's own device class** is an alias: `Detected`/`Clear` for
occupancy, `Open`/`Closed` for a door, `Low`/`Normal` for battery. Aliases are
resolved **per entity**, so `Closed` never matches a light that is off.

### String (enum)

The raw value always matches (`heat`, `below_horizon`, `playing`). HA's
translated form is an alias when it has one — by device class or translation
key: `Heat`, `Below horizon`, an enum sensor's option labels.

`unavailable` and `unknown` are ordinary values (`Unavailable`/`Unknown` alias).
All comparisons are case-insensitive. A numeric-looking entry never matches a
non-numeric state, and a word never matches a numeric state.

### Vocabulary and validation

Every entity has a **vocabulary**: the states it can be in, raw and translated,
taken from HA's own translation tables for its (domain, device_class) or
(platform, translation_key) — plus an enum sensor's `options`, plus its current
raw state. No table is kept by hand and no type annotation is asked of the user.

A word entry is **unmatched** when it is in the vocabulary of **none** of the
entities the other categories select. The result lists it under
`unmatched_values` with did-you-mean suggestions drawn from that same
vocabulary (`Cleat` → `Clear`). Matching is by membership; suggestions are only
hints — nothing is ever fuzzy-matched silently.

`sb_filter/values` returns that vocabulary for a filter, with how many selected
entities are currently in each state, so an editor can offer chips instead of a
text box. Chips store the raw value and show the translated label.

Aliases follow HA's configured language: `Clear` in an English install is
`off` everywhere.

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

## rate

Change of a **numeric** state per minute, hour or day: `>0.5/h`, `<=-2/h`,
`>=1/m`, `<0.1/d` — a comparator is required; entries are ORed. The rate is
(value now − the value **held** at the start of the window) ÷ the window. The
value held at now − `rate_window` is that of the latest sample at or before it
(a state is held until the next change). With no sample that old the rate is
**unknown and never matches** — a sensor with fifteen minutes of
history has no hourly rate yet. `rate_window` defaults to the largest unit used
(`/h` → 1 h); set it explicitly to measure over a different span (`30m`, `6h`).
`units` pins the quantity, as with ranges. Non-numeric states have no rate.
An unreadable entry is ignored and reported, like `state_for`.

Samples come from Home Assistant's recorder (seeded when an entity first
enters a rate filter's scope) and then live from state changes; a rate
subscription is re-evaluated every 60 s because the reference slides even
when no new sample arrives.

## Results

`ids` (sorted), `pattern_counts`, `configured`, `unreadable`, `unmatched_values`
(`[{value, suggestions}]`), `grammar` (this document's version). A subscription
re-sends only when `ids` change; state and registry changes coalesce into one
recompute per second, and a `state_for` term is re-evaluated every 30 s.

## Changes from v2

- `rate` and `rate_window` (this version). Nothing else changed.

## Changes from v1

- `states`: three typed kinds. A plain number is numeric **equality** (v1 compared
  it as a string, which happened to work for `100` but not `100.0`). Words never
  match numeric states; numbers never match words.
- `unmatched_values` with suggestions; the `sb_filter/values` command.
- Everything else is unchanged; v1 configs keep their meaning except the
  equality case above.
