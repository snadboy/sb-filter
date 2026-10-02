"""Home Assistant glue: build a Snapshot from the live registries, and keep a
filter's result current.

A selection moves only when the SET of candidate entities changes: an entity
appears or goes away, is renamed, changes device class or unit, or the
registries move it (labels, areas, devices). State VALUES never move it, so a
state change that leaves those alone is ignored without a recompute."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    label_registry as lr,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import DEBOUNCE_SECONDS, DOMAIN, GRAMMAR_VERSION, SIGNAL_SUBS
from .grammar import Filter, parse_filter
from .matcher import DeviceRow, EntityRow, MatchResult, Snapshot, StateRow, evaluate

_REGISTRY_EVENTS = (
    er.EVENT_ENTITY_REGISTRY_UPDATED,
    dr.EVENT_DEVICE_REGISTRY_UPDATED,
    ar.EVENT_AREA_REGISTRY_UPDATED,
    lr.EVENT_LABEL_REGISTRY_UPDATED,
)
_SELECTING_ATTRS = ("friendly_name", "device_class", "unit_of_measurement")


@callback
def selection_moved(data: dict) -> bool:
    """state_changed event filter (HA passes the event DATA): True when the
    change can alter what a filter selects."""
    old, new = data.get("old_state"), data.get("new_state")
    if old is None or new is None:
        return True                       # an entity appeared or went away
    return any(old.attributes.get(a) != new.attributes.get(a) for a in _SELECTING_ATTRS)


@callback
def build_snapshot(hass: HomeAssistant) -> Snapshot:
    """Plain data for the pure matcher."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    states = {s.entity_id: StateRow(attributes=s.attributes) for s in hass.states.async_all()}
    entities = {
        e.entity_id: EntityRow(device_id=e.device_id, area_id=e.area_id, labels=tuple(e.labels))
        for e in ent_reg.entities.values()
    }
    # `DeviceRegistry.devices` is a deprecation view (HA 2026.9 → removed 2027.9):
    # ITERATING it yields DeviceEntry values and is the supported form; any
    # mapping access (.values(), [], .get()) is reported. `EntityRegistry.entities`
    # is a plain container whose iteration yields KEYS — keep .values() there.
    devices = {d.id: DeviceRow(area_id=d.area_id, labels=tuple(d.labels)) for d in dev_reg.devices}
    return Snapshot(states=states, entities=entities, devices=devices)


@callback
def match_now(hass: HomeAssistant, config: dict[str, Any]) -> tuple[Filter, MatchResult]:
    flt = parse_filter(config)
    return flt, evaluate(flt, build_snapshot(hass))


def result_payload(flt: Filter, res: MatchResult) -> dict[str, Any]:
    return {
        "ids": list(res.ids),
        "pattern_counts": list(res.pattern_counts),
        "configured": res.configured,
        "unreadable": list(flt.unreadable),
        "grammar": GRAMMAR_VERSION,
    }


_SUB_SEQ = [0]


def live_subscriptions(hass: HomeAssistant) -> dict[int, "FilterSubscription"]:
    return hass.data.setdefault(DOMAIN, {}).setdefault("subs", {})


class FilterSubscription:
    """Push a filter's ids whenever they change: an entity added, removed,
    renamed or re-classed, or any registry change. Bursts coalesce into one
    recompute per DEBOUNCE_SECONDS; nothing is sent when the ids are unchanged.

    Every live subscription is registered in hass.data so the diagnostics
    sensor can list them (origin, config, matches, activity)."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any], send: Callable[[dict[str, Any]], None],
                 origin: str | None = None) -> None:
        self.hass = hass
        self.config = config
        self.origin = origin or "unknown"
        self.filter = parse_filter(config)
        self.send = send
        _SUB_SEQ[0] += 1
        self.id = _SUB_SEQ[0]
        self.started = dt_util.utcnow()
        self.last_change: datetime | None = None
        self.recomputes = 0
        self.pushes = 0
        self._last: tuple[str, ...] | None = None
        self._pending: CALLBACK_TYPE | None = None
        self._unsubs: list[CALLBACK_TYPE] = []

    @callback
    def start(self) -> None:
        self._unsubs.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._on_event, event_filter=selection_moved))
        for ev in _REGISTRY_EVENTS:
            self._unsubs.append(self.hass.bus.async_listen(ev, self._on_event))
        live_subscriptions(self.hass)[self.id] = self
        self._recompute(force=True)
        async_dispatcher_send(self.hass, SIGNAL_SUBS)

    @callback
    def stop(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs.clear()
        if self._pending:
            self._pending()
            self._pending = None
        if live_subscriptions(self.hass).pop(self.id, None) is not None:
            async_dispatcher_send(self.hass, SIGNAL_SUBS)

    def describe(self) -> dict[str, Any]:
        """Compact on purpose: the recorder drops attributes over 16 KB, and 40 of these must fit."""
        return {
            "id": self.id,
            "origin": self.origin,
            "matched": len(self._last or ()),
            "terms": [k for k in ("patterns", "labels", "areas", "device_classes", "units", "classes") if self.config.get(k) not in (None, "", [])],
            "unreadable": len(self.filter.unreadable),
            "started": self.started.isoformat(timespec="seconds"),
            "last_change": self.last_change.isoformat(timespec="seconds") if self.last_change else None,
            "recomputes": self.recomputes,
            "pushes": self.pushes,
        }

    @callback
    def _on_event(self, _event: Event) -> None:
        if self._pending is None:
            self._pending = async_call_later(self.hass, DEBOUNCE_SECONDS, self._fire)

    @callback
    def _fire(self, _now=None) -> None:
        self._pending = None
        self._recompute()

    @callback
    def _recompute(self, force: bool = False) -> None:
        res = evaluate(self.filter, build_snapshot(self.hass))
        self.recomputes += 1
        if force or res.ids != self._last:
            if res.ids != self._last:
                self.last_change = dt_util.utcnow()
            self._last = res.ids
            self.pushes += 1
            self.send(result_payload(self.filter, res))
            async_dispatcher_send(self.hass, SIGNAL_SUBS)
