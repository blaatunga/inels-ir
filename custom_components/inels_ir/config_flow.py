"""Add and reconfigure an eLAN-IR-003 gateway."""

import asyncio

from aiohttp import ClientError
import probatio as vol

from homeassistant import config_entries
from homeassistant.components.dhcp import async_discovered_service_info
from homeassistant.core import callback
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.selector import (
    SelectSelector, SelectSelectorConfig, TextSelector, TextSelectorConfig, TextSelectorType,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo

from .api import (
    DOMAIN,
    GatewayError,
    gateway_session,
    gateway_url,
    identify_gateway,
    learning_origin,
)

from .options_flow import InelsIrOptionsFlow


class InelsIrConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the gateway without transmitting any IR codes."""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return InelsIrOptionsFlow()

    _candidates: dict[str, DhcpServiceInfo]

    async def async_step_user(self, user_input=None):
        """Offer known DHCP candidates even if HA saw them before installation."""
        if user_input is not None:
            return await self._async_gateway_form("user", user_input)
        try:
            seen = async_discovered_service_info(self.hass)
        except KeyError:
            seen = []
        configured = self._async_current_entries()
        candidates = [
            item for item in seen
            if item.macaddress.replace(":", "").lower().startswith("2c6a6f")
            and not any(entry.data.get(CONF_MAC) == item.macaddress.replace(":", "").lower()
                        for entry in configured)
        ][:8]
        verified = await asyncio.gather(*(self._async_verify_candidate(item) for item in candidates))
        self._candidates = {
            host: item for host, item in zip(verified, candidates, strict=True) if host is not None
        }
        if self._candidates:
            return await self.async_step_choose_gateway()
        return await self._async_gateway_form("user", None)

    async def _async_verify_candidate(self, item: DhcpServiceInfo) -> str | None:
        try:
            address = str(item.ip)
            origin = gateway_url(f"[{address}]" if ":" in address else address)
            async with gateway_session() as session:
                mac = await identify_gateway(session, origin)
        except (ClientError, GatewayError, TimeoutError, ValueError):
            return None
        if mac == item.macaddress.replace(":", "").lower():
            return str(origin)
        return None

    async def async_step_choose_gateway(self, user_input=None):
        if user_input is not None:
            selection = user_input[CONF_HOST]
            if selection == "manual":
                return await self._async_gateway_form("user", None)
            return await self.async_step_dhcp(self._candidates[selection])
        options = [{"value": host, "label": host} for host in self._candidates]
        options.append({"value": "manual", "label": "IP / hostname"})
        return self.async_show_form(
            step_id="choose_gateway",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): SelectSelector(SelectSelectorConfig(options=options)),
            }),
        )

    async def async_step_reconfigure(self, user_input=None):
        """Edit the address or administrator credentials."""
        return await self._async_gateway_form("reconfigure", user_input)

    async def _async_gateway_form(self, step_id, user_input):
        entry = self._get_reconfigure_entry() if step_id == "reconfigure" else None
        defaults = {}
        if entry is not None:
            defaults = {
                CONF_HOST: entry.data[CONF_HOST],
                CONF_USERNAME: entry.data.get(CONF_USERNAME, ""),
            }

        errors = {}
        if user_input is not None:
            try:
                origin = str(gateway_url(user_input[CONF_HOST]))
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "")
            can_keep_password = (
                entry is not None
                and CONF_HOST not in errors
                and origin == entry.data[CONF_HOST]
                and username == entry.data.get(CONF_USERNAME)
            )
            if username and not password and can_keep_password:
                password = entry.data.get(CONF_PASSWORD, "")
            if bool(username) != bool(password):
                errors[CONF_PASSWORD] = "missing_credentials"
            if username and CONF_HOST not in errors:
                try:
                    learning_origin(gateway_url(origin))
                except GatewayError:
                    errors[CONF_HOST] = "private_address_required"

            if not errors:
                self._async_abort_entries_match({CONF_HOST: origin})
                mac = entry.data.get(CONF_MAC) if entry is not None else None
                if username or mac:
                    try:
                        async with gateway_session() as session:
                            observed_mac = await identify_gateway(session, gateway_url(origin))
                    except (ClientError, GatewayError, TimeoutError, ValueError):
                        errors[CONF_HOST] = "not_supported"
                    else:
                        if mac is not None and mac != observed_mac:
                            errors[CONF_HOST] = "gateway_changed"
                        else:
                            mac = observed_mac
                            self._async_abort_entries_match({CONF_MAC: mac})
                if not errors:
                    data = {CONF_HOST: origin}
                    if username:
                        data.update({CONF_USERNAME: username, CONF_PASSWORD: password})
                    if mac:
                        data[CONF_MAC] = mac
                    if entry is not None:
                        return self.async_update_reload_and_abort(entry, data=data)
                    if mac:
                        await self.async_set_unique_id(mac, raise_on_progress=False)
                        self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=origin, data=data)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): TextSelector(),
                vol.Optional(CONF_USERNAME): TextSelector(),
                vol.Optional(CONF_PASSWORD): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                schema,
                defaults if user_input is None else {
                    key: value for key, value in user_input.items() if key != CONF_PASSWORD
                },
            ),
            errors=errors,
        )
    _discovered_host: str | None = None
    _discovered_mac: str | None = None

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo):
        """Offer a gateway after a read-only model and MAC check."""
        try:
            address = str(discovery_info.ip)
            if ":" in address:
                address = f"[{address}]"
            origin = gateway_url(address)
            self._async_abort_entries_match({CONF_HOST: str(origin)})
            async with gateway_session() as session:
                mac = await identify_gateway(session, origin)
        except (ClientError, GatewayError, TimeoutError, ValueError):
            return self.async_abort(reason="not_supported")
        if mac != discovery_info.macaddress.replace(":", "").lower():
            return self.async_abort(reason="not_supported")
        self._async_abort_entries_match({CONF_MAC: mac})
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        self._discovered_host = str(origin)
        self._discovered_mac = mac
        self.context["title_placeholders"] = {"host": self._discovered_host}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        """Add the discovered gateway only after confirmation."""
        if user_input is None:
            return self.async_show_form(
                step_id="confirm",
                description_placeholders={"host": self._discovered_host},
            )
        self._async_abort_entries_match({CONF_HOST: self._discovered_host})
        self._async_abort_entries_match({CONF_MAC: self._discovered_mac})
        return self.async_create_entry(
            title=self._discovered_host,
            data={
                CONF_HOST: self._discovered_host,
                CONF_MAC: self._discovered_mac,
            },
        )

