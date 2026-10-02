"""Evaluate a Filter against a Snapshot. Pure: no Home Assistant imports, no clock.

The Snapshot is plain data so the same code runs under plain python3 with
fixtures (tests/vectors.json) and inside HA (ha.py builds it from the live
registries). Only an entity's id, friendly name, device class and unit are
read from its state object — never the state value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .grammar import Filter


@dataclass(frozen=True)
class StateRow:
    attributes: dict


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


def _unit(attrs: dict) -> str:
    u = attrs.get("unit_of_measurement")
    return str(u) if u is not None else ""


def evaluate(flt: Filter, snap: Snapshot) -> MatchResult:
    """Every configured category must pass; blank patterns never count."""
    counts = [0] * len(flt.patterns)
    if not flt.configured or flt.state_keys:
        return MatchResult(ids=(), pattern_counts=tuple(counts), configured=flt.configured)

    ids: list[str] = []
    active = flt.active_patterns
    for entity_id in sorted(snap.states):
        attrs = snap.states[entity_id].attributes
        name = attrs.get("friendly_name")

        ok = active == 0
        for i, pat in enumerate(flt.patterns):
            if pat is None:
                continue
            if all(t.search(entity_id) is not None or (name is not None and t.search(str(name)) is not None) for t in pat.tokens):
                counts[i] += 1
                ok = True
        if not ok:
            continue

        if flt.labels and not any(l in flt.labels for l in entity_labels(snap, entity_id)):
            continue
        if flt.areas and entity_area(snap, entity_id) not in flt.areas:
            continue
        dc = str(attrs.get("device_class") or "").lower()
        if flt.device_classes and dc not in flt.device_classes:
            continue
        if flt.units and _unit(attrs) not in flt.units:
            continue
        if flt.classes and not any((c is None or c == dc) and (u is None or u == _unit(attrs)) for c, u in flt.classes):
            continue
        ids.append(entity_id)
    return MatchResult(ids=tuple(ids), pattern_counts=tuple(counts), configured=True)
