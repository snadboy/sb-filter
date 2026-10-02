"""SB Filter — the one implementation of the SB entity-filter grammar:
WHICH entities (patterns, labels, areas, device class, unit), never their state.

Two kinds of config entry:
  - the engine (one, no options): the WebSocket API and sensor.sb_filter_live_filters;
  - a NAMED FILTER (data {"kind": "filter"}): a selection with a name and a sensor,
    picked by SB Watch rules and SB Entity Browser cards — the one place selections
    are made. Added from Integrations → SB Filter → Add entry, or the shared
    "Add filter" dialog (frontend/sb-filter-dialog.js) the cards, the SB Watch panel
    and the SB Filter sidebar page (frontend/sb-filter-panel.js, /sb-filter) open.
    See named.py and FILTER.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import DOMAIN, STATIC_URL
from .named import NamedFilter, is_filter_entry, notify_removed
from .websocket import async_register

__all__ = ["DOMAIN"]
_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
PANEL_URL = "sb-filter"                # the sidebar page: every named filter, what uses it (?edit=<entry_id>, ?add=1)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the WebSocket API and the dialog's static path once, whether we are set
    up by a config entry or pulled in as another integration's dependency."""
    data = hass.data.setdefault(DOMAIN, {})
    integration = await async_get_integration(hass, DOMAIN)
    data["version"] = str(integration.version) if integration.version else "0"
    if not data.get("ws_registered"):
        async_register(hass)
        data["ws_registered"] = True
        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), False)])
            if PANEL_URL not in hass.data.get("frontend_panels", {}):
                await panel_custom.async_register_panel(
                    hass, frontend_url_path=PANEL_URL, webcomponent_name="sb-filter-panel", sidebar_title="SB Filter",
                    sidebar_icon="mdi:filter-multiple-outline", module_url=f"{STATIC_URL}/sb-filter-panel.js?v={data['version']}",
                    embed_iframe=False, require_admin=True)
        except Exception:  # noqa: BLE001 — the dialog and the page are conveniences; filters work without them
            _LOGGER.exception("SB Filter: could not serve the filter dialog / sidebar page")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if is_filter_entry(entry):
        nf = NamedFilter(hass, entry)
        entry.runtime_data = nf
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        nf.start()
        entry.async_on_unload(entry.add_update_listener(_async_reload))
        return True
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """A filter was edited: update it in place (a reload would blank its sensor for a moment)."""
    nf = getattr(entry, "runtime_data", None)
    if not isinstance(nf, NamedFilter):
        await hass.config_entries.async_reload(entry.entry_id)
        return
    nf.update(entry)
    dev_reg = dr.async_get(hass)
    if (dev := dev_reg.async_get_device(identifiers={(DOMAIN, entry.entry_id)})) is not None and dev.name != nf.name:
        dev_reg.async_update_device(dev.id, name=nf.name)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if is_filter_entry(entry) and isinstance(getattr(entry, "runtime_data", None), NamedFilter):
        entry.runtime_data.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """A named filter was deleted: whoever follows it now selects nothing, and says why."""
    if is_filter_entry(entry):
        notify_removed(hass, entry.entry_id)
