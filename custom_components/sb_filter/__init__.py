"""SB Filter — the one implementation of the SB entity-filter grammar.

No entities. Consumers: the SB Entity Browser card (WebSocket subscription)
and SB Watch (imports the matcher directly). See FILTER.md for the grammar.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .websocket import async_register

__all__ = ["DOMAIN"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the WebSocket API once, whether we are set up by a config entry
    or pulled in as another integration's dependency."""
    data = hass.data.setdefault(DOMAIN, {})
    if not data.get("ws_registered"):
        async_register(hass)
        data["ws_registered"] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
