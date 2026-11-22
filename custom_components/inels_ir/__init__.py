"""Home Assistant integration for the ELKO EP eLAN-IR-003."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import GatewayCoordinator
from .learning import async_register_learning

PLATFORMS = [Platform.BUTTON]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register actions even before the first gateway is configured."""
    async_register_learning(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up the configured IR buttons."""
    coordinator = GatewayCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the configured IR buttons."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
