"""WebSocket API: one-shot match and a live subscription."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import GRAMMAR_VERSION
from .ha import FilterSubscription, async_match, result_payload, values_now


@websocket_api.websocket_command({vol.Required("type"): "sb_filter/match", vol.Required("config"): dict})
@websocket_api.async_response
async def ws_match(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    flt, res = await async_match(hass, msg["config"])
    connection.send_result(msg["id"], result_payload(flt, res))


@websocket_api.websocket_command({vol.Required("type"): "sb_filter/subscribe", vol.Required("config"): dict})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    sub = FilterSubscription(
        hass, msg["config"], lambda payload: connection.send_message(websocket_api.event_message(msg["id"], payload))
    )
    connection.subscriptions[msg["id"]] = sub.stop
    connection.send_result(msg["id"], {"grammar": GRAMMAR_VERSION})
    sub.start()


@websocket_api.websocket_command({vol.Required("type"): "sb_filter/values", vol.Required("config"): dict})
@callback
def ws_values(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """The vocabulary of the entities the filter's non-state categories select, with counts."""
    connection.send_result(msg["id"], {"values": values_now(hass, msg["config"]), "grammar": GRAMMAR_VERSION})


@websocket_api.websocket_command({vol.Required("type"): "sb_filter/info"})
@callback
def ws_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    connection.send_result(msg["id"], {"grammar": GRAMMAR_VERSION})


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_match)
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_values)
    websocket_api.async_register_command(hass, ws_info)
