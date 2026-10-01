"""The SB filter grammar: parsing only, no Home Assistant imports.

One filter = patterns ∧ labels ∧ areas ∧ device_classes ∧ units ∧ states ∧ state_for.
Within a category any entry matches (OR); every configured category must be
satisfied (AND); an empty category does not constrain. See FILTER.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PLACEHOLDER_PREFIX = "___"   # HA pickers emit "___no_items_available___" for an empty list

_RANGE_RX = re.compile(r"^(?:(<=|<|>=|>)\s*(-?\d+(?:\.\d+)?)|(-?\d+(?:\.\d+)?)\s*(?:\.\.|-)\s*(-?\d+(?:\.\d+)?))$")
_DUR_RX = re.compile(r"^(<=|<|>=|>)?\s*((?:\d+(?:\.\d+)?\s*[dhms]\s*)+|\d+(?:\.\d+)?)$", re.I)
_DUR_PART = re.compile(r"([\d.]+)([dhms])", re.I)
_UNIT_SECS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


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
class Token:
    regex: re.Pattern
    exact: str | None      # lower-cased token when it carries no wildcard: may equal a state exactly


@dataclass(frozen=True)
class Pattern:
    tokens: tuple[Token, ...]   # every token must match (AND), each anywhere in id or name, or a state exactly


def parse_pattern(p: Any) -> Pattern | None:
    """A blank pattern is None: it never constrains and never counts."""
    if p is None:
        return None
    s = str(p).strip()
    if not s:
        return None
    toks = tuple(
        Token(regex=glob_to_regex(t), exact=None if ("*" in t or "?" in t) else t.lower())
        for t in s.split()
    )
    return Pattern(tokens=toks)


@dataclass(frozen=True)
class Range:
    lo: float | None = None
    hi: float | None = None
    lo_open: bool = False   # True: strictly greater than lo
    hi_open: bool = False   # True: strictly less than hi

    def contains(self, n: float) -> bool:
        if self.lo is not None and (n <= self.lo if self.lo_open else n < self.lo):
            return False
        if self.hi is not None and (n >= self.hi if self.hi_open else n > self.hi):
            return False
        return True


def parse_range(s: Any) -> Range | None:
    """``<20 <=20 >80 >=80 20-50 20..50``; a span is inclusive and may be written either way round."""
    m = _RANGE_RX.match(str(s).strip())
    if not m:
        return None
    if m.group(3) is not None:
        a, b = float(m.group(3)), float(m.group(4))
        return Range(lo=min(a, b), hi=max(a, b))
    n = float(m.group(2))
    return {
        "<": Range(hi=n, hi_open=True),
        "<=": Range(hi=n),
        ">": Range(lo=n, lo_open=True),
        ">=": Range(lo=n),
    }[m.group(1)]


@dataclass(frozen=True)
class Duration:
    op: str        # < <= > >=
    seconds: float

    def holds(self, age_seconds: float) -> bool:
        return {
            "<": age_seconds < self.seconds,
            "<=": age_seconds <= self.seconds,
            ">": age_seconds > self.seconds,
            ">=": age_seconds >= self.seconds,
        }[self.op]


def parse_duration(v: Any) -> Duration | None:
    """``2h`` / ``>=2h`` at least; ``<5m`` within; d h m s combine (``1h30m``); a bare number is MINUTES."""
    if v is None or v == "":
        return None
    m = _DUR_RX.match(str(v).strip())
    if not m:
        return None
    body = re.sub(r"\s+", "", m.group(2))
    if re.fullmatch(r"[\d.]+", body):
        secs = float(body) * 60
    else:
        secs = sum(float(n) * _UNIT_SECS[u.lower()] for n, u in _DUR_PART.findall(body))
    return Duration(op=m.group(1) or ">=", seconds=secs)


_RATE_RX = re.compile(r"^(<=|<|>=|>)\s*(-?\d+(?:\.\d+)?)\s*/\s*([mhd])$", re.I)


@dataclass(frozen=True)
class RateTerm:
    op: str            # < <= > >=
    value: float       # in units per `per`
    per: str           # m h d
    per_seconds: float

    def holds(self, per_second: float) -> bool:
        r = per_second * self.per_seconds
        return {"<": r < self.value, "<=": r <= self.value, ">": r > self.value, ">=": r >= self.value}[self.op]


def parse_rate(v: Any) -> RateTerm | None:
    """``>0.5/h`` ``<-2/h`` ``>=1/m`` ``<0.1/d`` — change per minute/hour/day; comparator required."""
    if v is None or v == "":
        return None
    m = _RATE_RX.match(str(v).strip())
    if not m:
        return None
    per = m.group(3).lower()
    return RateTerm(op=m.group(1), value=float(m.group(2)), per=per, per_seconds=_UNIT_SECS[per])


def is_number(s: Any) -> float | None:
    """The float value of a numeric state, else None (``inf``/``nan`` are not states we range over)."""
    try:
        n = float(str(s).strip())
    except (TypeError, ValueError):
        return None
    if n != n or n in (float("inf"), float("-inf")):
        return None
    return n


@dataclass(frozen=True)
class Filter:
    patterns: tuple[Pattern | None, ...] = ()   # index-aligned with the config list (blanks kept as None)
    labels: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()
    device_classes: tuple[str, ...] = ()        # lower-cased
    units: tuple[str, ...] = ()                 # exact
    classes: tuple[tuple[str | None, str | None], ...] = ()   # (device_class lower | None, unit | None) PAIRS, ORed
    values: tuple[str, ...] = ()                # lower-cased WORD values (raw or translated); numbers became ranges
    value_text: tuple[str, ...] = ()            # the same words as typed, for the unmatched report
    ranges: tuple[Range, ...] = ()
    state_for: Duration | None = None
    rates: tuple[RateTerm, ...] = ()            # ORed; only numeric states have a rate
    rate_window: float | None = None            # seconds; default = the largest unit among the terms
    unreadable: tuple[str, ...] = ()            # things we could not parse, for the editor to show

    @property
    def active_patterns(self) -> int:
        return sum(1 for p in self.patterns if p is not None)

    @property
    def configured(self) -> bool:
        """Nothing configured = match NOTHING (never the whole estate)."""
        return bool(
            self.active_patterns or self.labels or self.areas or self.device_classes
            or self.units or self.classes or self.values or self.ranges or self.state_for or self.rates
        )


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
    """Parse a card / rule config into a Filter. Unknown keys are ignored."""
    c = config or {}
    unreadable: list[str] = []
    raw_patterns = c.get("patterns")
    if raw_patterns is None:
        raw_patterns = []
    elif not isinstance(raw_patterns, (list, tuple)):
        raw_patterns = [raw_patterns]
    patterns = tuple(parse_pattern(p) for p in raw_patterns)

    values: list[str] = []
    ranges: list[Range] = []
    for s in as_list(c.get("states")):
        r = parse_range(s)
        n = is_number(s) if r is None else None
        if r:
            ranges.append(r)
        elif n is not None:
            ranges.append(Range(lo=n, hi=n))          # v2: a plain number is numeric EQUALITY
        else:
            values.append(s.lower())
    lo, hi = is_number(c.get("state_min")), is_number(c.get("state_max"))
    if lo is not None or hi is not None:
        ranges.append(Range(lo=lo, hi=hi))

    dur = parse_duration(c.get("state_for"))
    if c.get("state_for") not in (None, "") and dur is None:
        unreadable.append(f"state_for: {c.get('state_for')}")

    rates: list[RateTerm] = []
    for r in as_list(c.get("rate")):
        term = parse_rate(r)
        if term:
            rates.append(term)
        else:
            unreadable.append(f"rate: {r}")
    window = None
    if rates:
        w = parse_duration(c.get("rate_window"))
        if c.get("rate_window") not in (None, "") and w is None:
            unreadable.append(f"rate_window: {c.get('rate_window')}")
        window = w.seconds if w else max(t.per_seconds for t in rates)

    raw_classes = c.get("classes")
    if raw_classes is None or raw_classes == "":
        raw_classes = []
    elif not isinstance(raw_classes, (list, tuple)):
        raw_classes = [raw_classes]
    classes = tuple(p for p in (parse_class(v) for v in raw_classes) if p is not None)

    return Filter(
        patterns=patterns,
        labels=tuple(as_list(c.get("labels"))),
        areas=tuple(as_list(c.get("areas"))),
        device_classes=tuple(s.lower() for s in as_list(c.get("device_classes"))),
        units=tuple(as_list(c.get("units"))),
        classes=classes,
        values=tuple(values),
        value_text=tuple(w for w in as_list(c.get("states")) if parse_range(w) is None and is_number(w) is None),
        ranges=tuple(ranges),
        state_for=dur,
        rates=tuple(rates),
        rate_window=window,
        unreadable=tuple(unreadable),
    )
