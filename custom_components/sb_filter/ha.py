"""Home Assistant glue: build a Snapshot from the live registries, and keep a
filter's result current (states, registries, and time all move it)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    label_registry as lr,
)
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.translation import async_translate_state
from homeassistant.util import dt as dt_util

from .const import DEBOUNCE_SECONDS, DOMAIN, DURATION_TICK_SECONDS, GRAMMAR_VERSION
from .grammar import Filter, parse_filter
from .matcher import DeviceRow, EntityRow, MatchResult, Snapshot, StateRow, evaluate

_REGISTRY_EVENTS = (
    er.EVENT_ENTITY_REGISTRY_UPDATED,
    dr.EVENT_DEVICE_REGISTRY_UPDATED,
    ar.EVENT_AREA_REGISTRY_UPDATED,
    lr.EVENT_LABEL_REGISTRY_UPDATED,
)


def _fmt_cache(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(DOMAIN, {}).setdefault("fmt_cache", {})


@callback
def build_snapshot(hass: HomeAssistant) -> Snapshot:
    """Plain data for the pure matcher. Translations are cached per (state, domain, platform, key, class)."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    states = {
        s.entity_id: StateRow(state=s.state, attributes=s.attributes, last_changed=s.last_changed)
        for s in hass.states.async_all()
    }
    entities = {
        e.entity_id: EntityRow(device_id=e.device_id, area_id=e.area_id, labels=tuple(e.labels))
        for e in ent_reg.entities.values()
    }
    # `DeviceRegistry.devices` is a deprecation view (HA 2026.9 → removed 2027.9):
    # ITERATING it yields DeviceEntry values and is the supported form; any
    # mapping access (.values(), [], .get()) is reported. `EntityRegistry.entities`
    # is a plain container whose iteration yields KEYS — keep .values() there.
    devices = {d.id: DeviceRow(area_id=d.area_id, labels=tuple(d.labels)) for d in dev_reg.devices}
    cache = _fmt_cache(hass)
    if len(cache) > 5000:
        cache.clear()

    def formatted(entity_id: str) -> str | None:
        row = states.get(entity_id)
        if row is None:
            return None
        entry = ent_reg.async_get(entity_id)
        platform = entry.platform if entry else None
        tkey = entry.translation_key if entry else None
        dclass = row.attributes.get("device_class")
        domain = entity_id.split(".", 1)[0]
        key = (row.state, domain, platform, tkey, dclass)
        if key not in cache:
            try:
                cache[key] = async_translate_state(hass, row.state, domain, platform, tkey, dclass)
            except Exception:  # noqa: BLE001 - a translation gap must never break matching
                cache[key] = row.state
        return cache[key]

    return Snapshot(states=states, entities=entities, devices=devices, formatted=formatted)


@callback
def match_now(hass: HomeAssistant, config: dict[str, Any]) -> tuple[Filter, MatchResult]:
    flt = parse_filter(config)
    return flt, evaluate(flt, build_snapshot(hass), dt_util.utcnow())


def result_payload(flt: Filter, res: MatchResult) -> dict[str, Any]:
    return {
        "ids": list(res.ids),
        "pattern_counts": list(res.pattern_counts),
        "configured": res.configured,
        "unreadable": list(flt.unreadable),
        "grammar": GRAMMAR_VERSION,
    }


class FilterSubscription:
    """Push a filter's ids whenever they change: any state change, any registry
    change, and (with a state_for term) the passage of time. Bursts coalesce
    into one recompute per DEBOUNCE_SECONDS; nothing is sent when the ids are unchanged."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any], send: Callable[[dict[str, Any]], None]) -> None:
        self.hass = hass
        self.filter = parse_filter(config)
        self.send = send
        self._last: tuple[str, ...] | None = None
        self._pending: CALLBACK_TYPE | None = None
        self._unsubs: list[CALLBACK_TYPE] = []

    @callback
    def start(self) -> None:
        self._unsubs.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._on_event))
        for ev in _REGISTRY_EVENTS:
            self._unsubs.append(self.hass.bus.async_listen(ev, self._on_event))
        if self.filter.state_for is not None:
            self._unsubs.append(
                async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=DURATION_TICK_SECONDS))
            )
        self._recompute(force=True)

    @callback
    def stop(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs.clear()
        if self._pending:
            self._pending()
            self._pending = None

    @callback
    def _on_event(self, _event: Event) -> None:
        self._schedule()

    @callback
    def _on_tick(self, _now) -> None:
        self._schedule()

    @callback
    def _schedule(self) -> None:
        if self._pending:
            return
        self._pending = async_call_later(self.hass, DEBOUNCE_SECONDS, self._fire)

    @callback
    def _fire(self, _now=None) -> None:
        self._pending = None
        self._recompute()

    @callback
    def _recompute(self, force: bool = False) -> None:
        res = evaluate(self.filter, build_snapshot(self.hass), dt_util.utcnow())
        if force or res.ids != self._last:
            self._last = res.ids
            self.send(result_payload(self.filter, res))
