"""One-click, single-instance config flow: there is nothing to configure."""

from __future__ import annotations

from homeassistant import config_entries

from .const import DOMAIN


class SbFilterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(title="SB Filter", data={})
