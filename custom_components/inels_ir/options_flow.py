"""Guide administrators through learning and assigning gateway IR signals."""

import asyncio

from aiohttp import ClientError
import probatio as vol

from homeassistant.config_entries import ConfigEntryState, OptionsFlow
from homeassistant.const import CONF_MAC, CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, TextSelector
from homeassistant.helpers.translation import async_get_translations

from .api import (
    DOMAIN, GatewayError, create_remote, gateway_admin, gateway_session, update_remote,
    update_remote_action,
)
from .learning import valid_gateway_text


class InelsIrOptionsFlow(OptionsFlow):
    """Expose gateway operations in the integration's settings."""

    _task: asyncio.Task | None = None
    _error: str = ""
    _device_id: str = ""

    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        if entry.state != ConfigEntryState.LOADED:
            return self.async_abort(reason="gateway_unavailable")
        if not entry.data.get(CONF_USERNAME) or not entry.data.get(CONF_PASSWORD):
            return self.async_abort(reason="credentials_required")
        choices = {"create_device": "Add remote", "learn": "Learn a new IR code"}
        if entry.runtime_data.data.slots:
            choices["assign"] = "Create an action from a stored code"
        if entry.runtime_data.data.devices:
            choices["edit_device"] = "Edit remote"
            if any(remote.actions for remote in entry.runtime_data.data.devices.values()):
                choices["edit_action"] = "Edit button"
        translations = await async_get_translations(
            self.hass, self.hass.config.language, "options", (DOMAIN,)
        )
        return self.async_show_menu(
            step_id="init",
            menu_options={
                step: translations.get(f"component.{DOMAIN}.options.step.init.menu_options.{step}")
                or fallback
                for step, fallback in choices.items()
            },
        )

    async def async_step_create_device(self, user_input=None):
        fields = ("label", "product", "manufacturer", "description", "device_type")
        errors = {}
        if user_input is not None:
            metadata = {field: user_input.get(field, "").strip() for field in fields}
            errors = {
                field: "invalid_text" for field, value in metadata.items()
                if not valid_gateway_text(value)
            }
            if not metadata["label"]:
                errors["label"] = "name_required"
            if not errors:
                return await self._async_write(create_remote, metadata)
        schema = vol.Schema({
            (vol.Required if field == "label" else vol.Optional)(field): TextSelector()
            for field in fields
        })
        return self.async_show_form(
            step_id="create_device",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

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
        devices = sorted({device.name for device in self.config_entry.runtime_data.data.devices.values()})
        fields = {
            names("device_name"): (
                SelectSelector(SelectSelectorConfig(options=devices, custom_value=True))
                if devices else TextSelector()
            ),
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

    async def async_step_edit_device(self, user_input=None):
        return await self._async_select_device("edit_device", user_input)

    async def async_step_edit_action(self, user_input=None):
        return await self._async_select_device("edit_action", user_input)

    async def _async_select_device(self, step_id, user_input):
        remotes = self.config_entry.runtime_data.data.devices
        if user_input is not None:
            self._device_id = user_input["device_id"]
            if self._device_id not in remotes:
                return self.async_abort(reason="gateway_unavailable")
            if step_id == "edit_device":
                return await self.async_step_device_metadata()
            return await self.async_step_action_details()
        options = [
            {"value": key, "label": remote.name}
            for key, remote in remotes.items()
            if step_id != "edit_action" or remote.actions
        ]
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required("device_id"): SelectSelector(SelectSelectorConfig(options=options)),
            }),
        )

    async def async_step_device_metadata(self, user_input=None):
        remote = self.config_entry.runtime_data.data.devices.get(self._device_id)
        if remote is None:
            return self.async_abort(reason="gateway_unavailable")
        fields = ("label", "product", "manufacturer", "description", "device_type")
        errors = {}
        if user_input is not None:
            fields_to_update = {
                key: value.strip() for key, value in user_input.items()
                if key in fields and value.strip() != remote.metadata.get(key, "")
            }
            errors = {
                key: "invalid_text" for key, value in fields_to_update.items()
                if not valid_gateway_text(value)
            }
            if not errors:
                if fields_to_update:
                    return await self._async_write(update_remote, self._device_id, fields_to_update)
                return await self.async_step_done()
        schema = vol.Schema({
            vol.Optional(field): TextSelector() for field in fields
        })
        return self.async_show_form(
            step_id="device_metadata",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input if user_input is not None else remote.metadata
            ),
            errors=errors,
        )

    async def async_step_action_details(self, user_input=None):
        catalog = self.config_entry.runtime_data.data
        remote = catalog.devices.get(self._device_id)
        if remote is None:
            return self.async_abort(reason="gateway_unavailable")
        errors = {}
        if user_input is not None:
            label = user_input.get("label", "").strip()
            if not valid_gateway_text(label, action_key=True):
                errors["label"] = "invalid_text"
            else:
                changes = {
                    key: int(user_input[key]) for key in ("ir_slot", "ir_output")
                    if key in user_input
                }
                return await self._async_write(
                    update_remote_action, self._device_id, user_input["action_id"],
                    label=label, **changes,
                )
        fields = {
            vol.Required("action_id"): SelectSelector(SelectSelectorConfig(options=[
                {"value": key, "label": value} for key, value in remote.actions.items()
            ])),
            vol.Optional("label"): TextSelector(),
            vol.Optional("ir_output"): SelectSelector(SelectSelectorConfig(options=["1", "2", "3"])),
        }
        if catalog.slots:
            fields[vol.Optional("ir_slot")] = SelectSelector(
                SelectSelectorConfig(options=[str(slot) for slot in catalog.slots])
            )
        return self.async_show_form(step_id="action_details", data_schema=vol.Schema(fields), errors=errors)

    async def _async_write(self, operation, *args, **kwargs):
        entry = self.config_entry
        coordinator = entry.runtime_data
        username = entry.data.get(CONF_USERNAME)
        password = entry.data.get(CONF_PASSWORD)
        mac = entry.data.get(CONF_MAC)
        if not username or not password or not mac:
            return self.async_abort(reason="credentials_required")
        if entry.state != ConfigEntryState.LOADED or coordinator.lock.locked():
            return self.async_abort(reason="gateway_unavailable")
        try:
            async with coordinator.lock, gateway_session() as session:
                async with gateway_admin(session, coordinator.origin, username, password, mac) as origin:
                    await operation(session, origin, *args, **kwargs)
        except (ClientError, TimeoutError, ValueError, GatewayError) as err:
            self._error = str(err) if isinstance(err, GatewayError) else type(err).__name__
            return await self.async_step_failed()
        finally:
            if entry.state == ConfigEntryState.LOADED and entry.runtime_data is coordinator:
                await coordinator.async_refresh()
        return await self.async_step_done()

    async def async_step_done(self, user_input=None):
        return self.async_abort(reason="saved_on_gateway")

    async def async_step_failed(self, user_input=None):
        return self.async_abort(reason="gateway_operation_failed",
                                description_placeholders={"error": self._error})
