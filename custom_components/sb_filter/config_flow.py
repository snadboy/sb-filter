"""Config flow.

The first entry is the ENGINE (one click, nothing to configure). Every entry
after it is a NAMED FILTER: a name and a selection — patterns, areas, labels,
class:unit pairs. The options flow edits a filter the same way. The shared
"Add filter" dialog (frontend/sb-filter-dialog.js) posts this same form over
the REST API, so there is one validation path.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import COMMON_CLASSES, DOMAIN, KIND_FILTER
from .grammar import as_list, parse_filter
from .ha import match_now
from .named import filter_entries, is_filter_entry, selection_of


def _chips(values: list[str], extra: tuple[str, ...] = ()) -> selector.SelectSelector:
    opts = list(dict.fromkeys([*values, *extra]))
    return selector.SelectSelector(selector.SelectSelectorConfig(options=opts, multiple=True, custom_value=True,
                                                               mode=selector.SelectSelectorMode.DROPDOWN))


def _schema(d: dict[str, Any]) -> vol.Schema:
    pats, classes = as_list(d.get("patterns")), as_list(d.get("classes"))
    return vol.Schema({
        vol.Required("name", default=d.get("name", "")): selector.TextSelector(),
        vol.Optional("patterns", default=pats): _chips(pats),
        vol.Optional("areas", default=list(d.get("areas") or [])): selector.AreaSelector(selector.AreaSelectorConfig(multiple=True)),
        vol.Optional("labels", default=list(d.get("labels") or [])): selector.LabelSelector(selector.LabelSelectorConfig(multiple=True)),
        vol.Optional("classes", default=classes): _chips(classes, COMMON_CLASSES),
    })


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"name": str(user_input.get("name") or "").strip()}
    # a chip may still carry commas (a client posting one string)
    out["patterns"] = [p for item in as_list(user_input.get("patterns")) for p in as_list(item)]
    for k in ("areas", "labels"):
        out[k] = as_list(user_input.get(k))
    out["classes"] = [c for c in as_list(user_input.get("classes")) if c.strip(": ")]
    return out


def _validate(hass, opts: dict[str, Any], own_entry_id: str | None) -> dict[str, str]:
    if not opts["name"]:
        return {"name": "no_name"}
    if any((e.options.get("name") or e.title).strip().lower() == opts["name"].lower() and e.entry_id != own_entry_id
           for e in filter_entries(hass)):
        return {"name": "name_taken"}
    if not parse_filter(selection_of(opts)).configured:
        return {"base": "empty"}
    return {}


PANEL_ADD = "[Open the SB Filter page](/sb-filter?add=1) — every filter, what uses it, and the same form with a live list."


def _live(hass, opts: dict[str, Any]) -> dict[str, str]:
    sel = selection_of(opts)
    if not sel:
        return {"count": "Nothing selected yet."}
    _, res = match_now(hass, sel)
    n = len(res.ids)
    return {"count": f"Selects **{n}** {'entity' if n == 1 else 'entities'} now."}


class SbFilterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if not any(not is_filter_entry(e) for e in self._async_current_entries()):
            # the engine first: one click, nothing to configure
            if user_input is None:
                return self.async_show_form(step_id="engine")
            return await self.async_step_engine(user_input)
        return await self._filter_step(user_input)

    async def async_step_engine(self, user_input: dict[str, Any] | None = None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="engine")
        return self.async_create_entry(title="SB Filter", data={})

    async def async_step_import(self, data: dict[str, Any]):
        """From SB Watch's migration (a rule's own selection becomes a named filter)."""
        opts = _clean(data)
        errors = _validate(self.hass, opts, None)
        if errors:
            return self.async_abort(reason=next(iter(errors.values())))
        return self.async_create_entry(title=opts["name"], data={"kind": KIND_FILTER}, options=opts)

    async def _filter_step(self, user_input: dict[str, Any] | None):
        errors: dict[str, str] = {}
        shown: dict[str, Any] = {}
        if user_input is not None:
            opts = _clean(user_input)
            errors = _validate(self.hass, opts, None)
            if not errors:
                return self.async_create_entry(title=opts["name"], data={"kind": KIND_FILTER}, options=opts)
            shown = opts
        return self.async_show_form(step_id="user", data_schema=_schema(shown), errors=errors,
                                    description_placeholders={**_live(self.hass, shown), "panel": PANEL_ADD})

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return SbFilterOptionsFlow()

    @classmethod
    @callback
    def async_supports_options_flow(cls, entry: config_entries.ConfigEntry) -> bool:
        return is_filter_entry(entry)          # the engine has nothing to configure


class SbFilterOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if not is_filter_entry(entry):
            return self.async_abort(reason="engine")
        errors: dict[str, str] = {}
        shown = dict(entry.options)
        if user_input is not None:
            opts = _clean(user_input)
            errors = _validate(self.hass, opts, entry.entry_id)
            if not errors:
                self.hass.config_entries.async_update_entry(entry, title=opts["name"])
                return self.async_create_entry(title="", data=opts)
            shown = opts
        return self.async_show_form(step_id="init", data_schema=_schema(shown), errors=errors,
                                    description_placeholders={**_live(self.hass, shown),
                                                              "panel": f"[Open the SB Filter page](/sb-filter?edit={entry.entry_id}) — every filter, what uses it, and a live list of what this one selects."})
