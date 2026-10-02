# SB filter grammar — version 5

One filter **selects entities**: which ones, never what state they are in. It is
the config of an SB Entity Browser card and the selection of an SB Watch rule;
`sb_filter` is its only implementation.

```yaml
patterns: [fp300 $q$, "light."]     # OR between patterns; words within one pattern AND
labels: [matter_hub]                 # entity's own labels OR its device's
areas: [kitchen]                     # entity's area, else its device's
device_classes: [battery]            # attribute device_class, case-insensitive
units: ["%"]                         # attribute unit_of_measurement, exact
classes: ["battery:%", temperature, ":°F"]   # device class AND unit as PAIRS, ORed — see "classes"
```

**Across categories: AND.** Every category that is configured must be satisfied.
An empty category does not constrain. **Within a category: OR.**

**Nothing configured matches nothing** — never the whole estate. SB Filter's own
sensors (a named filter's `sensor.<name>_filter`, the Live filters sensor) are never
selected.

## What a filter is not

Everything about **state** — a value (`on`, `Detected`), a range (`<20`), time in
state, a rate of change — belongs to **SB Watch**: a rule there is this
selection plus trigger rows. A dashboard that wants "batteries under 20 %" points
its SB Entity Browser at such a rule (`rule: sensor.<rule>_count`).

Grammar 4 also had `states`, `state_min`, `state_max`, `state_for`, `rate` and
`rate_window`. A config that still carries any of them **selects nothing**,
reports each in `unreadable`, and stays `configured` — silently widening
"batteries under 20 %" to every battery would be worse than an empty list.

## patterns

A pattern is whitespace-separated tokens; **all tokens must match** (AND). A token
matches when, case-insensitively, it is found **anywhere** in the entity id
(wildcards implied on both ends) or anywhere in the friendly name.

`*` = any run, `?` = one character. A blank pattern is ignored (it never excludes
anything and never counts). Each pattern reports how many entities it matched
(`pattern_counts`, index-aligned with the list).

## labels, areas

Lists of ids. An entity carries a label itself **or through its device** — HA
does not propagate device labels. An entity is in its own area, else its device's.
HA picker placeholders (`___no_items_available___`) are dropped.

## device_classes, units

Lists (or comma strings). Device class compares case-insensitively; unit exactly.
`sensor.*battery` alone also catches battery *voltage* sensors; a device class or
unit pins the quantity.

## classes

`device_classes` and `units` are two independent lists: `[battery, temperature]`
with `["%", "°F"]` also admits a battery sensor in °F. `classes` pairs them.
Each entry is `class:unit`, with either side optional — `battery:%`,
`temperature`, `:°F` — or the object form `{device_class: battery, unit: "%"}`.
An entity satisfies the category when it satisfies **any one** entry, and an
entry is satisfied when the class matches (case-insensitive, if given) **and**
the unit matches (exact, if given). `classes` is its own category: it is ANDed
with everything else, including `device_classes` and `units` if those are set.
SB Watch's rule form writes `classes`; cards may use either.

## Results

`ids` (sorted), `pattern_counts`, `configured`, `unreadable`, `grammar` (this
document's version). A subscription re-sends only when `ids` change. It
recomputes on registry changes (labels, areas, devices, entities) and on a
state change that adds or removes an entity or changes its friendly name, device
class or unit — never on a change of state value alone. Bursts coalesce into one
recompute per second.

## Changes from v4

- **Selection only.** `states`, `state_min`, `state_max`, `state_for`, `rate` and
  `rate_window` moved to SB Watch (its `condition` module carries their vectors).
  A config with any of them selects nothing and says so in `unreadable`.
- A pattern token no longer matches a state exactly (`CR2450` used to find the
  battery-type sensors reporting CR2450). Patterns match ids and names only.
- `unmatched_values` and the `sb_filter/values` command are gone; SB Watch's
  `sb_watch/values` and `sb_watch/preview` answer state questions for editors.

## Changes from v3

- `classes`: device class and unit as pairs.

## Changes from v2

- `rate` and `rate_window`.

## Changes from v1

- `states`: three typed kinds; `unmatched_values`; the `sb_filter/values` command.
