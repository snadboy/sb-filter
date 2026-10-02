"""The SB filter grammar: parsing only, no Home Assistant imports.

One filter = patterns ∧ labels ∧ areas ∧ device_classes ∧ units ∧ classes —
WHICH entities, never what state they are in (that is SB Watch's job).
Within a category any entry matches (OR); every configured category must be
satisfied (AND); an empty category does not constrain. See FILTER.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PLACEHOLDER_PREFIX = "___"   # HA pickers emit "___no_items_available___" for an empty list
# Grammar 4 also judged state. A config that still carries one of these selects
# NOTHING and says why: silently widening "batteries under 20 %" to every
# battery would be worse than an empty list.
STATE_KEYS = ("states", "state_min", "state_max", "state_for", "rate", "rate_window")


def as_list(v: Any) -> list[str]:
    """A list, a comma string (a Param Card's $p$), one value, or nothing → list of stripped strings.

    Picker placeholders (``___…``) are dropped.
    """
    if v is None or v == "":
        return []
    items = v if isinstance(v, (list, tuple)) else str(v).split(",")
    out = []
    for s in items:
        s = str(s if s is not None else "").strip()
        if s and not s.startswith(PLACEHOLDER_PREFIX):
            out.append(s)
    return out


def glob_to_regex(glob: str) -> re.Pattern:
    """``*`` → any run, ``?`` → one char, everything else literal; searched anywhere, case-insensitive."""
    esc = "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in glob)
    return re.compile(esc, re.I)


@dataclass(frozen=True)
class Pattern:
    tokens: tuple[re.Pattern, ...]   # every token must match (AND), each anywhere in the id or the friendly name


def parse_pattern(p: Any) -> Pattern | None:
    """A blank pattern is None: it never constrains and never counts."""
    if p is None:
        return None
    s = str(p).strip()
    if not s:
        return None
    return Pattern(tokens=tuple(glob_to_regex(t) for t in s.split()))


@dataclass(frozen=True)
class Filter:
    patterns: tuple[Pattern | None, ...] = ()   # index-aligned with the config list (blanks kept as None)
    labels: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()
    device_classes: tuple[str, ...] = ()        # lower-cased
    units: tuple[str, ...] = ()                 # exact
    classes: tuple[tuple[str | None, str | None], ...] = ()   # (device_class lower | None, unit | None) PAIRS, ORed
    state_keys: tuple[str, ...] = ()            # grammar-4 state keys present: the filter selects nothing
    unreadable: tuple[str, ...] = ()            # things we could not use, for the editor to show

    @property
    def active_patterns(self) -> int:
        return sum(1 for p in self.patterns if p is not None)

    @property
    def configured(self) -> bool:
        """Nothing configured = match NOTHING (never the whole estate)."""
        return bool(self.active_patterns or self.labels or self.areas or self.device_classes
                    or self.units or self.classes or self.state_keys)


def parse_class(v: Any) -> tuple[str | None, str | None] | None:
    """One `classes` entry → (device_class, unit); either side may be absent.

    ``battery:%`` · ``temperature`` · ``:°F`` · ``{device_class: battery, unit: "%"}``.
    The device class is case-insensitive, the unit exact — as in `device_classes` / `units`.
    """
    if isinstance(v, dict):
        dc, unit = v.get("device_class"), v.get("unit")
    else:
        s = str(v if v is not None else "")
        dc, _, unit = s.partition(":")
    dc = str(dc).strip().lower() if dc not in (None, "") and str(dc).strip() else None
    unit = str(unit).strip() if unit not in (None, "") and str(unit).strip() else None
    if dc is None and unit is None:
        return None
    return dc, unit


def parse_filter(config: dict[str, Any] | None) -> Filter:
    """Parse a card / rule config into a Filter. Unknown keys are ignored; state keys are refused."""
    c = config or {}
    raw_patterns = c.get("patterns")
    if raw_patterns is None:
        raw_patterns = []
    elif not isinstance(raw_patterns, (list, tuple)):
        raw_patterns = [raw_patterns]

    raw_classes = c.get("classes")
    if raw_classes is None or raw_classes == "":
        raw_classes = []
    elif not isinstance(raw_classes, (list, tuple)):
        raw_classes = [raw_classes]

    state_keys = tuple(k for k in STATE_KEYS if c.get(k) not in (None, "", []))
    return Filter(
        patterns=tuple(parse_pattern(p) for p in raw_patterns),
        labels=tuple(as_list(c.get("labels"))),
        areas=tuple(as_list(c.get("areas"))),
        device_classes=tuple(s.lower() for s in as_list(c.get("device_classes"))),
        units=tuple(as_list(c.get("units"))),
        classes=tuple(p for p in (parse_class(v) for v in raw_classes) if p is not None),
        state_keys=state_keys,
        unreadable=tuple(f"{k}: state conditions belong to SB Watch (grammar 5)" for k in state_keys),
    )
