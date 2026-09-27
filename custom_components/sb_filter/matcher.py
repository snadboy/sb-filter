"""Evaluate a Filter against a Snapshot. Pure: no Home Assistant imports, no clock.

The Snapshot is plain data so the same code runs under pytest with fixtures
(tests/vectors.json) and inside HA (ha.py builds it from the live registries).
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class MatchResult:
    ids: tuple[str, ...]
    pattern_counts: tuple[int, ...]   # index-aligned with the config's pattern list
    configured: bool


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


def evaluate(flt: Filter, snap: Snapshot, now: datetime) -> MatchResult:
    """Every configured category must pass; blank patterns never count."""
    counts = [0] * len(flt.patterns)
    if not flt.configured:
        return MatchResult(ids=(), pattern_counts=tuple(counts), configured=False)

    ids: list[str] = []
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
        if flt.values or flt.ranges:
            hit = bool(flt.values) and (raw_l in flt.values or fmt_l in flt.values)
            if not hit and flt.ranges:
                n = is_number(row.state)
                hit = n is not None and any(r.contains(n) for r in flt.ranges)
            if not hit:
                continue
        if flt.state_for is not None:
            age = (now - row.last_changed).total_seconds()
            if not flt.state_for.holds(age):
                continue
        ids.append(entity_id)
    return MatchResult(ids=tuple(ids), pattern_counts=tuple(counts), configured=True)
