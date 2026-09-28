"""Evaluate a Filter against a Snapshot. Pure: no Home Assistant imports, no clock.

The Snapshot is plain data so the same code runs under pytest with fixtures
(tests/vectors.json) and inside HA (ha.py builds it from the live registries).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .grammar import Filter, is_number


@dataclass(frozen=True)
class StateRow:
    state: str
    attributes: dict
    last_changed: datetime       # aware


@dataclass(frozen=True)
class EntityRow:
    device_id: str | None = None
    area_id: str | None = None
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeviceRow:
    area_id: str | None = None
    labels: tuple[str, ...] = ()


@dataclass
class Snapshot:
    states: dict[str, StateRow]
    entities: dict[str, EntityRow] = field(default_factory=dict)
    devices: dict[str, DeviceRow] = field(default_factory=dict)
    # entity_id -> displayed (translated) state for NON-numeric states; numeric states format as themselves
    formatted: Callable[[str], str | None] = lambda entity_id: None
    # entity_id -> the states it can be in, as (raw, translated-or-None) pairs, from HA's
    # translation tables (domain/device_class or platform/translation_key) and enum options.
    # The current raw state is always added by the matcher. Numeric entities have none.
    vocabulary: Callable[[str], list[tuple[str, str | None]]] = lambda entity_id: []


@dataclass(frozen=True)
class Unmatched:
    value: str
    suggestions: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    ids: tuple[str, ...]
    pattern_counts: tuple[int, ...]   # index-aligned with the config's pattern list
    configured: bool
    unmatched_values: tuple[Unmatched, ...] = ()


def entity_labels(snap: Snapshot, entity_id: str) -> tuple[str, ...]:
    """The entity's own labels plus its DEVICE's (HA does not propagate device labels)."""
    reg = snap.entities.get(entity_id)
    if reg is None:
        return ()
    own = list(reg.labels)
    if reg.device_id and (dev := snap.devices.get(reg.device_id)):
        own.extend(dev.labels)
    return tuple(dict.fromkeys(own))


def entity_area(snap: Snapshot, entity_id: str) -> str | None:
    """The entity's area, else its device's."""
    reg = snap.entities.get(entity_id)
    if reg is None:
        return None
    if reg.area_id:
        return reg.area_id
    if reg.device_id and (dev := snap.devices.get(reg.device_id)):
        return dev.area_id
    return None


def _formatted(snap: Snapshot, entity_id: str, row: StateRow) -> str:
    if is_number(row.state) is not None:
        return row.state
    return snap.formatted(entity_id) or row.state


def entity_vocabulary(snap: Snapshot, entity_id: str, row: StateRow) -> list[tuple[str, str | None]]:
    """Every state this entity can be in: HA's table for it, plus its current raw state."""
    if is_number(row.state) is not None:
        return []
    vocab = list(snap.vocabulary(entity_id) or [])
    raws = {r.lower() for r, _ in vocab}
    if row.state.lower() not in raws:
        vocab.append((row.state, snap.formatted(entity_id)))
    return vocab


def _word_matches(flt: Filter, snap: Snapshot, entity_id: str, row: StateRow) -> bool:
    raw_l = row.state.lower()
    if raw_l in flt.values:
        return True
    fmt = snap.formatted(entity_id)
    return fmt is not None and fmt.lower() in flt.values


def _validate_values(flt: Filter, snap: Snapshot, selected: list[str]) -> tuple[Unmatched, ...]:
    """Words that are in NO selected entity's vocabulary, with did-you-mean from that vocabulary."""
    if not flt.value_text:
        return ()
    words: dict[str, tuple[str, str]] = {}   # lower word -> (as spelled, raw state key)
    for entity_id in selected:
        row = snap.states[entity_id]
        for raw, translated in entity_vocabulary(snap, entity_id, row):
            for w in (translated, raw):        # translated first: it is the form to suggest
                if w:
                    words.setdefault(w.lower(), (w, raw.lower()))
    out = []
    for typed in flt.value_text:
        if typed.lower() in words:
            continue
        close = difflib.get_close_matches(typed.lower(), list(words), n=6, cutoff=0.75)
        seen: set[str] = set()
        picks: list[str] = []
        for c in close:                        # one suggestion per underlying state
            spelled, key = words[c]
            if key in seen:
                continue
            seen.add(key)
            picks.append(spelled)
        out.append(Unmatched(value=typed, suggestions=tuple(picks[:3])))
    return tuple(out)


def evaluate(flt: Filter, snap: Snapshot, now: datetime) -> MatchResult:
    """Every configured category must pass; blank patterns never count."""
    counts = [0] * len(flt.patterns)
    if not flt.configured:
        return MatchResult(ids=(), pattern_counts=tuple(counts), configured=False)

    ids: list[str] = []
    pre_state: list[str] = []            # passed everything except states/state_for: the validation scope
    active = flt.active_patterns
    for entity_id in sorted(snap.states):
        row = snap.states[entity_id]
        name = row.attributes.get("friendly_name")
        fmt = _formatted(snap, entity_id, row)
        raw_l = row.state.lower()
        fmt_l = fmt.lower()

        ok = active == 0
        for i, pat in enumerate(flt.patterns):
            if pat is None:
                continue
            hit = all(
                t.regex.search(entity_id) is not None
                or (name is not None and t.regex.search(str(name)) is not None)
                or (t.exact is not None and (raw_l == t.exact or fmt_l == t.exact))
                for t in pat.tokens
            )
            if hit:
                counts[i] += 1
                ok = True
        if not ok:
            continue

        if flt.labels and not any(l in flt.labels for l in entity_labels(snap, entity_id)):
            continue
        if flt.areas and entity_area(snap, entity_id) not in flt.areas:
            continue
        if flt.device_classes and str(row.attributes.get("device_class") or "").lower() not in flt.device_classes:
            continue
        if flt.units and str(row.attributes.get("unit_of_measurement") if row.attributes.get("unit_of_measurement") is not None else "") not in flt.units:
            continue
        pre_state.append(entity_id)
        if flt.values or flt.ranges:
            # Three kinds of state: a numeric state meets only ranges/equality;
            # a word state meets only words (raw or translated alias).
            n = is_number(row.state)
            if n is not None:
                hit = any(r.contains(n) for r in flt.ranges)
            else:
                hit = _word_matches(flt, snap, entity_id, row)
            if not hit:
                continue
        if flt.state_for is not None:
            age = (now - row.last_changed).total_seconds()
            if not flt.state_for.holds(age):
                continue
        ids.append(entity_id)
    return MatchResult(
        ids=tuple(ids), pattern_counts=tuple(counts), configured=True,
        unmatched_values=_validate_values(flt, snap, pre_state),
    )


def values(flt: Filter, snap: Snapshot) -> list[dict]:
    """The vocabulary of the entities the filter's NON-state categories select, with how
    many of them are currently in each state — for an editor's chips."""
    scoped = Filter(patterns=flt.patterns, labels=flt.labels, areas=flt.areas, device_classes=flt.device_classes, units=flt.units)
    res = evaluate(scoped, snap, datetime.max.replace(tzinfo=None)) if scoped.configured else None
    selected = list(res.ids) if res else sorted(snap.states)
    table: dict[str, dict] = {}
    for entity_id in selected:
        row = snap.states[entity_id]
        for raw, translated in entity_vocabulary(snap, entity_id, row):
            key = raw.lower()
            item = table.setdefault(key, {"value": raw, "label": translated or raw, "possible": 0, "current": 0})
            item["possible"] += 1
            if row.state.lower() == key:
                item["current"] += 1
    return sorted(table.values(), key=lambda i: (-i["current"], -i["possible"], i["label"].lower()))
