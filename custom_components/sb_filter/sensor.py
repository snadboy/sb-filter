"""Two kinds of sensor.

The engine's entry: sensor.sb_filter_live_filters — how many filters are being
watched right now, each described in the attributes (understanding, debugging).

A named filter's entry: sensor.<name>_filter — how many entities it selects, with
their ids in `entity_ids` (what SB Watch rules and SB Entity Browser cards read)."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.loader import async_get_integration

from .const import DOMAIN, GRAMMAR_VERSION, SIGNAL_SUBS
from .ha import live_subscriptions
from .named import NamedFilter, is_filter_entry

MAX_LISTED = 40   # ~180 bytes each → well under the recorder's 16 KB attribute cap


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    version = str(integration.version) if integration.version else None
    if is_filter_entry(entry):
        add([FilterSensor(entry, entry.runtime_data, version)])
    else:
        add([LiveFiltersSensor(hass, entry, version)])


class FilterSensor(SensorEntity):
    """A named filter: how many entities it selects; the ids in `entity_ids`."""

    _attr_has_entity_name = True
    _attr_name = "Filter"
    _attr_icon = "mdi:filter-outline"
    _attr_should_poll = False
    _attr_native_unit_of_measurement = "entities"
    _unrecorded_attributes = frozenset({"entity_ids"})   # can be long; the count carries the history

    def __init__(self, entry: ConfigEntry, nf: NamedFilter, version: str | None) -> None:
        self._nf = nf
        self._attr_unique_id = f"{entry.entry_id}_filter"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, entry_type=DeviceEntryType.SERVICE, name=nf.name,
            manufacturer="snadboy", model="SB Filter · named filter", sw_version=version,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._nf.add_entity_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return self._nf.payload is not None

    @property
    def native_value(self) -> int | None:
        return len(self._nf.ids) if self._nf.payload is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        p = self._nf.payload or {}
        return {
            "entity_ids": list(self._nf.ids),
            "selection": self._nf.selection,
            "filter_id": self._nf.entry_id,
            "unreadable": p.get("unreadable") or [],
            "grammar": GRAMMAR_VERSION,
        }


class LiveFiltersSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Live filters"
    _attr_icon = "mdi:filter-multiple-outline"
    _attr_should_poll = False
    _attr_native_unit_of_measurement = "filters"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, version: str | None) -> None:
        self._hass = hass
        self._attr_unique_id = f"{entry.entry_id}_live_filters"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, entry_type=DeviceEntryType.SERVICE, name="SB Filter",
            manufacturer="snadboy", model="Entity-filter engine", sw_version=version,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self._hass, SIGNAL_SUBS, self._changed))

    @callback
    def _changed(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return len(live_subscriptions(self._hass))

    @property
    def extra_state_attributes(self) -> dict:
        subs = sorted(live_subscriptions(self._hass).values(), key=lambda s: s.id)
        return {
            "grammar": GRAMMAR_VERSION,
            "filters": [s.describe() for s in subs[:MAX_LISTED]],
            "not_listed": max(0, len(subs) - MAX_LISTED),
            "rules": sum(1 for s in subs if s.origin.startswith("rule:")),
            "named_filters": sum(1 for s in subs if s.origin.startswith("filter:")),
            "cards": sum(1 for s in subs if not s.origin.startswith(("rule:", "filter:"))),
        }
