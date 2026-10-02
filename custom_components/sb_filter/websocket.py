"""WebSocket API: one-shot match, a live subscription, the named filters, info."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, GRAMMAR_VERSION, STATIC_URL
from .ha import FilterSubscription, match_now, result_payload
from .named import filter_entries, named_filters, selection_of


@websocket_api.websocket_command({vol.Required("type"): "sb_filter/match", vol.Required("config"): dict})
@callback
def ws_match(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    flt, res = match_now(hass, msg["config"])
    connection.send_result(msg["id"], result_payload(flt, res))


@websocket_api.websocket_command({vol.Required("type"): "sb_filter/subscribe", vol.Required("config"): dict, vol.Optional("origin"): str})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    who = getattr(getattr(connection, "user", None), "name", None) or "?"
    origin = f"{msg.get('origin') or 'card'} · {who}"
    sub = FilterSubscription(
        hass, msg["config"], lambda payload: connection.send_message(websocket_api.event_message(msg["id"], payload)), origin=origin
    )
    connection.subscriptions[msg["id"]] = sub.stop
    connection.send_result(msg["id"], {"grammar": GRAMMAR_VERSION})
    sub.start()


@websocket_api.websocket_command({vol.Required("type"): "sb_filter/info"})
@callback
def ws_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    version = hass.data.get(DOMAIN, {}).get("version") or "0"
    connection.send_result(msg["id"], {"grammar": GRAMMAR_VERSION, "version": version,
                                       "dialog_url": f"{STATIC_URL}/sb-filter-dialog.js?v={version}"})


@websocket_api.websocket_command({vol.Required("type"): "sb_filter/filters"})
@callback
def ws_filters(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Every named filter: {entry_id, name, entity_id, selection, count}, sorted by name."""
    reg = er.async_get(hass)
    out = []
    for e in filter_entries(hass):
        nf = named_filters(hass).get(e.entry_id)
        out.append({
            "entry_id": e.entry_id,
            "name": e.options.get("name") or e.title,
            "entity_id": reg.async_get_entity_id("sensor", DOMAIN, f"{e.entry_id}_filter"),
            "selection": selection_of(e.options),
            "count": len(nf.ids) if nf and nf.payload is not None else None,
        })
    connection.send_result(msg["id"], {"filters": sorted(out, key=lambda f: f["name"].lower())})


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_match)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_info)
    websocket_api.async_register_command(hass, ws_filters)
