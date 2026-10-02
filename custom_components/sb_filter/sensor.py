"""sensor.sb_filter_live_filters: how many filters are being watched right now,
with each one described in the attributes — for understanding and debugging."""

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

MAX_LISTED = 40   # ~180 bytes each → well under the recorder's 16 KB attribute cap


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add: AddEntitiesCallback) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    add([LiveFiltersSensor(hass, entry, str(integration.version) if integration.version else None)])


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
            "cards": sum(1 for s in subs if not s.origin.startswith("rule:")),
        }
