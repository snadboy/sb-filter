"""Named filters: a selection with a name, owned by SB Filter, used by reference.

Each named filter is a config entry of this integration (data {"kind": "filter"},
options {name, patterns, areas, labels, classes}) with a SERVICE device and one
sensor (`sensor.<name>_filter`: state = how many entities, attribute `entity_ids`).
SB Watch rules and SB Entity Browser cards pick a filter instead of writing their
own selection — one place where selections are made.

In-process consumers (SB Watch) listen through `async_listen(hass, entry_id, cb)`.
The listener registry outlives the filter's own entry, so editing a filter (which
reloads its entry) hands the consumer the new ids without a gap: nothing is sent
on unload, only on removal (`missing`).
"""

from __future__ import annotations

from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .const import DOMAIN, GRAMMAR_VERSION, KIND_FILTER
from .grammar import as_list
from .ha import FilterSubscription

SELECTION_FIELDS = ("patterns", "areas", "labels", "classes")


def is_filter_entry(entry: ConfigEntry) -> bool:
    return (entry.data or {}).get("kind") == KIND_FILTER


def selection_of(options: dict[str, Any]) -> dict[str, Any]:
    """The grammar config a filter entry's options describe (empty categories left out)."""
    out: dict[str, Any] = {}
    for k in SELECTION_FIELDS:
        v = [s for s in as_list(options.get(k)) if s.strip(": ")] if k == "classes" else as_list(options.get(k))
        if v:
            out[k] = v
    return out


def _data(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(DOMAIN, {})


def _listeners(hass: HomeAssistant) -> dict[str, list[Callable[[dict[str, Any]], None]]]:
    return _data(hass).setdefault("named_listeners", {})


def named_filters(hass: HomeAssistant) -> dict[str, "NamedFilter"]:
    return _data(hass).setdefault("named", {})


class NamedFilter:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry_id = entry.entry_id
        self.name: str = entry.options.get("name") or entry.title
        self.selection: dict[str, Any] = selection_of(entry.options)
        self.payload: dict[str, Any] | None = None
        self._entity_cbs: list[Callable[[], None]] = []
        self._sub = FilterSubscription(hass, self.selection, self._on, origin=f"filter: {self.name}")

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple((self.payload or {}).get("ids") or ())

    @callback
    def start(self) -> None:
        named_filters(self.hass)[self.entry_id] = self
        self._sub.start()

    @callback
    def stop(self) -> None:
        self._sub.stop()
        if named_filters(self.hass).get(self.entry_id) is self:
            named_filters(self.hass).pop(self.entry_id)

    @callback
    def update(self, entry: ConfigEntry) -> None:
        """An edit: swap the selection IN PLACE — no reload, so the sensor never
        passes through unavailable / zero entities on its way to the new set."""
        self.name = entry.options.get("name") or entry.title
        self.selection = selection_of(entry.options)
        old = self._sub
        self._sub = FilterSubscription(self.hass, self.selection, self._on, origin=f"filter: {self.name}")
        self._sub.start()                       # pushes the new ids straight away
        old.stop()

    @callback
    def add_entity_listener(self, cb: Callable[[], None]) -> CALLBACK_TYPE:
        self._entity_cbs.append(cb)
        return lambda: self._entity_cbs.remove(cb)

    @callback
    def _on(self, payload: dict[str, Any]) -> None:
        self.payload = {**payload, "filter": self.entry_id, "name": self.name}
        for cb in list(self._entity_cbs):
            cb()
        for cb in list(_listeners(self.hass).get(self.entry_id, ())):
            cb(self.payload)


@callback
def async_listen(hass: HomeAssistant, entry_id: str, cb: Callable[[dict[str, Any]], None]) -> CALLBACK_TYPE:
    """Follow a named filter's ids: `cb(payload)` now if it is loaded, then on every change.
    A deleted filter sends `{ids: [], missing: True}`."""
    _listeners(hass).setdefault(entry_id, []).append(cb)
    nf = named_filters(hass).get(entry_id)
    if nf is not None and nf.payload is not None:
        cb(nf.payload)
    elif not any(e.entry_id == entry_id for e in hass.config_entries.async_entries(DOMAIN)):
        cb(missing_payload(entry_id))

    @callback
    def _unsub() -> None:
        lst = _listeners(hass).get(entry_id) or []
        if cb in lst:
            lst.remove(cb)
    return _unsub


def missing_payload(entry_id: str) -> dict[str, Any]:
    return {"ids": [], "configured": False, "missing": True, "filter": entry_id, "grammar": GRAMMAR_VERSION,
            "unreadable": [f"filter {entry_id}: not found — was it deleted?"]}


@callback
def notify_removed(hass: HomeAssistant, entry_id: str) -> None:
    for cb in list(_listeners(hass).get(entry_id, ())):
        cb(missing_payload(entry_id))


@callback
def filter_entries(hass: HomeAssistant) -> list[ConfigEntry]:
    return [e for e in hass.config_entries.async_entries(DOMAIN) if is_filter_entry(e)]


@callback
def find_by_selection(hass: HomeAssistant, selection: dict[str, Any]) -> ConfigEntry | None:
    """An existing filter whose selection is exactly this one (list order ignored)."""
    def norm(sel: dict[str, Any]) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in sel.items()}
    want = norm(selection_of(selection))
    for e in filter_entries(hass):
        if norm(selection_of(e.options)) == want:
            return e
    return None


async def async_find_or_create(hass: HomeAssistant, name: str, selection: dict[str, Any]) -> str:
    """The entry id of a filter with exactly this selection — an existing one, or a new one named `name`."""
    found = find_by_selection(hass, selection)
    if found is not None:
        return found.entry_id
    taken = {(e.options.get("name") or e.title).strip().lower() for e in filter_entries(hass)}
    base, n = name.strip() or "Filter", 1
    while (name if n == 1 else f"{base} {n}").lower() in taken:
        n += 1
    name = base if n == 1 else f"{base} {n}"
    res = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "import"}, data={"name": name, **selection_of(selection)})
    if res.get("type") != "create_entry":
        raise ValueError(f"could not create filter {name!r}: {res.get('reason') or res.get('errors')}")
    return res["result"].entry_id


# ---- who uses a filter ------------------------------------------------------------
# Integrations that reference named filters (SB Watch) register a provider; SB Filter
# never reads another integration's settings. A provider returns
#   {filter_entry_id: [{"kind": "SB Watch rule", "name": …, "url": …}, …]}
# Dashboard cards are found by the panel itself (it can read every dashboard).


@callback
def register_usage(hass: HomeAssistant, source: str, provider: Callable[[], dict[str, list[dict[str, Any]]]]) -> CALLBACK_TYPE:
    _data(hass).setdefault("usage", {})[source] = provider

    @callback
    def _unregister() -> None:
        _data(hass).get("usage", {}).pop(source, None)
    return _unregister


@callback
def usage(hass: HomeAssistant) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for provider in list(_data(hass).get("usage", {}).values()):
        try:
            found = provider() or {}
        except Exception:  # noqa: BLE001 — one broken provider must not hide the others
            continue
        for fid, users in found.items():
            out.setdefault(fid, []).extend(users)
    return out
