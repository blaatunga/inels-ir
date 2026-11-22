"""Guide administrators through learning and assigning gateway IR signals."""

import asyncio

import probatio as vol

from homeassistant.config_entries import ConfigEntryState, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, TextSelector

from .api import DOMAIN


class InelsIrOptionsFlow(OptionsFlow):
    """Expose gateway operations in the integration's settings."""

    _task: asyncio.Task | None = None
    _error: str = ""

    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        if entry.state != ConfigEntryState.LOADED:
            return self.async_abort(reason="gateway_unavailable")
        if not entry.data.get(CONF_USERNAME) or not entry.data.get(CONF_PASSWORD):
            return self.async_abort(reason="credentials_required")
        choices = ["learn"]
        if entry.runtime_data.data.slots:
            choices.append("assign")
        return self.async_show_menu(step_id="init", menu_options=choices)

    async def async_step_learn(self, user_input=None):
        return await self._async_command_form("learn", user_input)

    async def async_step_assign(self, user_input=None):
        return await self._async_command_form("assign", user_input)

    async def _async_command_form(self, step_id, user_input):
        if self._task is not None:
            if not self._task.done():
                return self.async_show_progress(
                    step_id=step_id, progress_action=step_id, progress_task=self._task
                )
            try:
                self._task.result()
            except HomeAssistantError as err:
                self._error = str(err)
                return self.async_show_progress_done(next_step_id="failed")
            return self.async_show_progress_done(next_step_id="done")

        if user_input is not None:
            data = {**user_input, "config_entry": self.config_entry.entry_id}
            for key in ("ir_slot", "ir_output"):
                if key in data:
                    data[key] = int(data[key])
            self._task = self.hass.async_create_task(
                self.hass.services.async_call(DOMAIN, "learn_code", data, blocking=True),
                "iNELS IR catalog operation",
            )
            return self.async_show_progress(
                step_id=step_id, progress_action=step_id, progress_task=self._task
            )

        names = vol.Required if step_id == "assign" else vol.Optional
        fields = {
            names("device_name"): TextSelector(),
            names("button_name"): TextSelector(),
            vol.Optional("ir_output", default="1"): SelectSelector(
                SelectSelectorConfig(options=["1", "2", "3"])
            ),
        }
        if step_id == "assign":
            fields[vol.Required("ir_slot")] = SelectSelector(
                SelectSelectorConfig(
                    options=[str(slot) for slot in self.config_entry.runtime_data.data.slots]
                )
            )
        return self.async_show_form(step_id=step_id, data_schema=vol.Schema(fields))

    async def async_step_done(self, user_input=None):
        return self.async_abort(reason="saved_on_gateway")

    async def async_step_failed(self, user_input=None):
        return self.async_abort(reason="gateway_operation_failed",
                                description_placeholders={"error": self._error})
