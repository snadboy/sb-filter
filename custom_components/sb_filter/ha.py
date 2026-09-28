"""Home Assistant glue: build a Snapshot from the live registries, and keep a
filter's result current (states, registries, and time all move it)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
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
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.translation import async_get_cached_translations, async_translate_state
from homeassistant.util import dt as dt_util

from .const import DEBOUNCE_SECONDS, DOMAIN, DURATION_TICK_SECONDS, GRAMMAR_VERSION, RATE_MAX_SAMPLES, RATE_TICK_SECONDS, SIGNAL_SUBS
from .grammar import is_number
from .grammar import Filter, parse_filter
from .matcher import DeviceRow, EntityRow, MatchResult, Snapshot, StateRow, evaluate, values as matcher_values

_REGISTRY_EVENTS = (
    er.EVENT_ENTITY_REGISTRY_UPDATED,
    dr.EVENT_DEVICE_REGISTRY_UPDATED,
    ar.EVENT_AREA_REGISTRY_UPDATED,
    lr.EVENT_LABEL_REGISTRY_UPDATED,
)


def _fmt_cache(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(DOMAIN, {}).setdefault("fmt_cache", {})


def _vocab_cache(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(DOMAIN, {}).setdefault("vocab_cache", {})


@callback
def _vocabulary_for(hass: HomeAssistant, domain: str, device_class: str | None, platform: str | None,
                    translation_key: str | None) -> list[tuple[str, str | None]]:
    """The states HA's translation tables know for this kind of entity: (raw, translated).

    Keys look like  component.<domain>.entity_component.<device_class|_>.state.<raw>
    and, for an entity with its own vocabulary,
                    component.<platform>.entity.<domain>.<translation_key>.state.<raw>
    — exactly what async_translate_state reads, so the aliases can never disagree."""
    lang = hass.config.language
    found: dict[str, str] = {}
    if platform and translation_key:
        prefix = f"component.{platform}.entity.{domain}.{translation_key}.state."
        for k, v in async_get_cached_translations(hass, lang, "entity", platform).items():
            if k.startswith(prefix) and "." not in k[len(prefix):]:
                found[k[len(prefix):]] = v
    if not found:
        table = async_get_cached_translations(hass, lang, "entity_component", domain)
        for dc in ((device_class or "_"), "_"):
            prefix = f"component.{domain}.entity_component.{dc}.state."
            for k, v in table.items():
                if k.startswith(prefix) and "." not in k[len(prefix):]:
                    found.setdefault(k[len(prefix):], v)
            if found:
                break
    return [(raw, label) for raw, label in found.items()]


class RateTracker:
    """Numeric sample buffers for the entities a rate term needs.

    Seeded from the recorder once per entity (so a one-shot match and a cold
    start can answer immediately), then appended live from state_changed. Kept
    only for entities somebody asked about; capped per entity."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.buffers: dict[str, deque] = {}
        self.window: dict[str, float] = {}         # entity -> longest window requested (s)
        self._seeded: set[str] = set()
        self._unsub: CALLBACK_TYPE | None = None

    @callback
    def samples(self, entity_id: str, window: float) -> list[tuple[datetime, float]]:
        return list(self.buffers.get(entity_id, ()))

    @callback
    def release_all(self) -> None:
        """No live filter uses a rate any more: drop every buffer and stop listening.
        The next rate filter re-seeds from the recorder, so nothing is lost."""
        self.buffers.clear()
        self.window.clear()
        self._seeded.clear()
        if self._unsub:
            self._unsub()
            self._unsub = None

    def _listen(self) -> None:
        if self._unsub is None:
            self._unsub = self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._on_state)

    @callback
    def _on_state(self, event: Event) -> None:
        new = event.data.get("new_state")
        if new is None or new.entity_id not in self.buffers:
            return
        n = is_number(new.state)
        if n is None:
            return
        buf = self.buffers[new.entity_id]
        buf.append((new.last_updated, n))
        self._trim(new.entity_id)

    def _trim(self, entity_id: str) -> None:
        buf = self.buffers[entity_id]
        keep_from = dt_util.utcnow() - timedelta(seconds=self.window.get(entity_id, 0) * 2 + 60)
        while len(buf) > 1 and buf[0][0] < keep_from and buf[1][0] <= keep_from:
            buf.popleft()          # keep one sample older than the window as the reference

    async def ensure(self, entity_ids: list[str], window: float) -> bool:
        """Seed buffers for any of these entities not yet tracked. Returns True if anything was seeded."""
        self._listen()
        todo = []
        for e in entity_ids:
            self.window[e] = max(self.window.get(e, 0), window)
            if e not in self._seeded:
                self._seeded.add(e)
                self.buffers.setdefault(e, deque(maxlen=RATE_MAX_SAMPLES))
                todo.append(e)
        if not todo:
            return False
        try:
            from homeassistant.components.recorder import get_instance, history  # noqa: PLC0415
        except ImportError:
            return True
        start = dt_util.utcnow() - timedelta(seconds=window * 2 + 60)

        def _fetch(ids: list[str]) -> dict[str, list]:
            out = {}
            for e in ids:
                out[e] = history.state_changes_during_period(
                    self.hass, start, None, entity_id=e, no_attributes=True, include_start_time_state=True,
                ).get(e, [])
            return out

        for i in range(0, len(todo), 50):
            chunk = todo[i:i + 50]
            try:
                rows = await get_instance(self.hass).async_add_executor_job(_fetch, chunk)
            except Exception:  # noqa: BLE001 - recorder off or busy: buffers fill live instead
                continue
            for e, states in rows.items():
                buf = self.buffers[e]
                have = {ts for ts, _ in buf}
                for st in states:
                    n = is_number(st.state)
                    if n is not None and st.last_updated not in have:
                        buf.append((st.last_updated, n))
                srt = sorted(buf)
                buf.clear(); buf.extend(srt)
        return True


def rate_tracker(hass: HomeAssistant) -> RateTracker:
    data = hass.data.setdefault(DOMAIN, {})
    if "rates" not in data:
        data["rates"] = RateTracker(hass)
    return data["rates"]


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

    vcache = _vocab_cache(hass)

    def vocabulary(entity_id: str) -> list[tuple[str, str | None]]:
        row = states.get(entity_id)
        if row is None:
            return []
        entry = ent_reg.async_get(entity_id)
        platform = entry.platform if entry else None
        tkey = entry.translation_key if entry else None
        dclass = row.attributes.get("device_class")
        domain = entity_id.split(".", 1)[0]
        key = (domain, dclass, platform, tkey)
        if key not in vcache:
            try:
                vcache[key] = _vocabulary_for(hass, domain, dclass, platform, tkey)
            except Exception:  # noqa: BLE001
                vcache[key] = []
        vocab = list(vcache[key])
        options = row.attributes.get("options")          # enum sensors carry their own list
        if isinstance(options, (list, tuple)):
            known = {r.lower() for r, _ in vocab}
            for o in options:
                if str(o).lower() not in known:
                    vocab.append((str(o), None))
        return vocab

    tracker = rate_tracker(hass)
    return Snapshot(states=states, entities=entities, devices=devices, formatted=formatted, vocabulary=vocabulary,
                    history=tracker.samples)


def _scope_ids(hass: HomeAssistant, flt: Filter) -> list[str]:
    """Entities the filter's non-rate categories select — the ones whose history a rate term needs."""
    scoped = Filter(patterns=flt.patterns, labels=flt.labels, areas=flt.areas, device_classes=flt.device_classes, units=flt.units,
                    values=flt.values, ranges=flt.ranges, state_for=flt.state_for)
    if scoped.configured:
        ids = list(evaluate(scoped, build_snapshot(hass), dt_util.utcnow()).ids)
    else:
        ids = [st.entity_id for st in hass.states.async_all()]        # a rate alone: every numeric entity
    out = []
    for e in ids:
        st = hass.states.get(e)
        if st is not None and is_number(st.state) is not None:
            out.append(e)
    return out


async def async_prepare_rates(hass: HomeAssistant, flt: Filter) -> bool:
    """Seed rate buffers for what this filter needs. True if new entities were seeded."""
    if not flt.rates:
        return False
    return await rate_tracker(hass).ensure(_scope_ids(hass, flt), flt.rate_window or 0)


@callback
def match_now(hass: HomeAssistant, config: dict[str, Any]) -> tuple[Filter, MatchResult]:
    flt = parse_filter(config)
    return flt, evaluate(flt, build_snapshot(hass), dt_util.utcnow())


async def async_match(hass: HomeAssistant, config: dict[str, Any]) -> tuple[Filter, MatchResult]:
    """match_now, after seeding any rate history the filter needs."""
    flt = parse_filter(config)
    await async_prepare_rates(hass, flt)
    return flt, evaluate(flt, build_snapshot(hass), dt_util.utcnow())


def result_payload(flt: Filter, res: MatchResult) -> dict[str, Any]:
    return {
        "ids": list(res.ids),
        "pattern_counts": list(res.pattern_counts),
        "configured": res.configured,
        "unreadable": list(flt.unreadable),
        "unmatched_values": [{"value": u.value, "suggestions": list(u.suggestions)} for u in res.unmatched_values],
        "grammar": GRAMMAR_VERSION,
    }


@callback
def values_now(hass: HomeAssistant, config: dict[str, Any]) -> list[dict]:
    return matcher_values(parse_filter(config), build_snapshot(hass))


_SUB_SEQ = [0]


def live_subscriptions(hass: HomeAssistant) -> dict[int, "FilterSubscription"]:
    return hass.data.setdefault(DOMAIN, {}).setdefault("subs", {})


class FilterSubscription:
    """Push a filter's ids whenever they change: any state change, any registry
    change, and (with a state_for term) the passage of time. Bursts coalesce
    into one recompute per DEBOUNCE_SECONDS; nothing is sent when the ids are unchanged.

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
        self._seeding = False

    @callback
    def start(self) -> None:
        self._unsubs.append(self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._on_event))
        for ev in _REGISTRY_EVENTS:
            self._unsubs.append(self.hass.bus.async_listen(ev, self._on_event))
        if self.filter.state_for is not None:
            self._unsubs.append(
                async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=DURATION_TICK_SECONDS))
            )
        live_subscriptions(self.hass)[self.id] = self
        if self.filter.rates:
            self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=RATE_TICK_SECONDS)))
            self.hass.async_create_task(self._seed_then_recompute())
        else:
            self._recompute(force=True)
        async_dispatcher_send(self.hass, SIGNAL_SUBS)

    async def _seed_then_recompute(self) -> None:
        try:
            await async_prepare_rates(self.hass, self.filter)
        finally:
            if self._unsubs:                 # still running
                self._recompute(force=True)

    @callback
    def stop(self) -> None:
        for u in self._unsubs:
            u()
        self._unsubs.clear()
        if self._pending:
            self._pending()
            self._pending = None
        if live_subscriptions(self.hass).pop(self.id, None) is not None:
            if self.filter.rates and not any(s.filter.rates for s in live_subscriptions(self.hass).values()):
                rate_tracker(self.hass).release_all()      # the last rate filter just left
            async_dispatcher_send(self.hass, SIGNAL_SUBS)

    def describe(self) -> dict[str, Any]:
        """Compact on purpose: the recorder drops attributes over 16 KB, and 60 of these must fit."""
        return {
            "id": self.id,
            "origin": self.origin,
            "matched": len(self._last or ()),
            "terms": [k for k in ("patterns", "labels", "areas", "device_classes", "units", "states", "state_for", "rate") if self.config.get(k) not in (None, "", [])],
            "unreadable": len(self.filter.unreadable),
            "started": self.started.isoformat(timespec="seconds"),
            "last_change": self.last_change.isoformat(timespec="seconds") if self.last_change else None,
            "recomputes": self.recomputes,
            "pushes": self.pushes,
        }

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
        self.recomputes += 1
        if force or res.ids != self._last:
            changed = res.ids != self._last
            self._last = res.ids
            self.pushes += 1
            if changed:
                self.last_change = dt_util.utcnow()
            self.send(result_payload(self.filter, res))
            async_dispatcher_send(self.hass, SIGNAL_SUBS)
        if self.filter.rates and not self._seeding:
            # entities newly in scope (renamed, added) get their history seeded, then one more pass
            self._seeding = True
            async def _more():
                try:
                    if await async_prepare_rates(self.hass, self.filter) and self._unsubs:
                        self._recompute()
                finally:
                    self._seeding = False
            self.hass.async_create_task(_more())
