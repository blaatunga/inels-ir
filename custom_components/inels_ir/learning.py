"""Learn IR signals directly on the gateway."""

from aiohttp import ClientError
import probatio as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_MAC, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .api import DOMAIN, GatewayError, gateway_session, learn_code

_LEGACY_OBJECT_KEYS = {
    "__defineGetter__", "__defineSetter__", "__lookupGetter__", "__lookupSetter__",
    "__proto__", "constructor", "hasOwnProperty", "isPrototypeOf",
    "propertyIsEnumerable", "toLocaleString", "toString", "valueOf",
}


def async_register_learning(hass: HomeAssistant) -> None:
    """Register the administrator action for learning a signal."""

    async def handle_learn(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data["config_entry"])
        if entry is None or entry.domain != DOMAIN or entry.state != ConfigEntryState.LOADED:
            raise HomeAssistantError("Select an active iNELS IR gateway")

        username = entry.data.get(CONF_USERNAME)
        password = entry.data.get(CONF_PASSWORD)
        mac = entry.data.get(CONF_MAC)
        if not username or not password or not mac:
            raise HomeAssistantError("Set administrator credentials in Reconfigure")

        label = call.data.get("button_name", "").strip()
        device = call.data.get("device_name", "").strip()
        if bool(label) != bool(device) or any(
            len(name) > 80
            or len(name.splitlines()) > 1
            or any(ord(c) < 32 or c in "<>&\"'" for c in name)
            for name in (label, device)
        ) or label in _LEGACY_OBJECT_KEYS:
            raise HomeAssistantError(
                "Use plain-text device and button names together, or leave both blank"
            )

        coordinator = entry.runtime_data
        if coordinator.lock.locked():
            raise HomeAssistantError("The iNELS IR gateway is busy. Try again shortly.")
        try:
            async with coordinator.lock, gateway_session() as session:
                code = await learn_code(
                    session,
                    coordinator.origin,
                    username,
                    password,
                    mac,
                    device_name=device,
                    button_name=label,
                    ir_output=call.data["ir_output"],
                )
        except (ClientError, TimeoutError, ValueError, GatewayError) as err:
            detail = str(err) if isinstance(err, GatewayError) else type(err).__name__
            raise HomeAssistantError(f"Could not finish IR learning ({detail})") from None
        finally:
            if entry.state == ConfigEntryState.LOADED and entry.runtime_data is coordinator:
                await coordinator.async_refresh()

        return {"code_id": int(code)}

    async_register_admin_service(
        hass,
        DOMAIN,
        "learn_code",
        handle_learn,
        schema=vol.Schema({
            vol.Required("config_entry"): cv.string,
            vol.Optional("button_name"): cv.string,
            vol.Optional("device_name"): cv.string,
            vol.Optional("ir_output", default=1): vol.All(int, vol.Range(min=1, max=3)),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
