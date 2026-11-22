"""Expose gateway IR slots and device actions as Home Assistant buttons."""

from aiohttp import ClientError

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry, entity_registry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DOMAIN, GatewayError, gateway_session, send_action, send_code
from .coordinator import GatewayCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Keep the entity registry in sync after each successful catalog read."""
    coordinator: GatewayCoordinator = entry.runtime_data
    registry = entity_registry.async_get(hass)
    devices = device_registry.async_get(hass)
    hub_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="ELKO EP",
        model="eLAN-IR-003",
        name="iNELS IR",
        configuration_url=str(coordinator.origin),
    )
    hub = devices.async_get_or_create(config_entry_id=entry.entry_id, **hub_info)
    known: set[str] = set()
    device_prefix = f"{entry.entry_id}:gateway:"
    refresh_id = f"{entry.entry_id}:refresh_catalog"

    @callback
    def sync_catalog() -> None:
        if not coordinator.last_update_success:
            return
        catalog = coordinator.data
        current = {}
        for slot in catalog.slots:
            unique_id = f"{entry.entry_id}_{slot}"
            current[unique_id] = (hub_info, None, str(slot), f"IR {slot}")
        current_device_ids = {hub.id}
        for device_id, remote in catalog.devices.items():
            info = DeviceInfo(
                identifiers={(DOMAIN, f"{device_prefix}{device_id}")},
                name=remote.name,
                manufacturer=remote.metadata.get("manufacturer"),
                model=remote.metadata.get("product"),
                via_device_id=hub.id,
            )
            registered = devices.async_get_or_create(config_entry_id=entry.entry_id, **info)
            current_device_ids.add(registered.id)
            for action_id, label in remote.actions.items():
                unique_id = f"{entry.entry_id}:action:{device_id}:{action_id}"
                current[unique_id] = (info, device_id, action_id, label)

        for entity in entity_registry.async_entries_for_config_entry(registry, entry.entry_id):
            if (
                entity.platform != DOMAIN
                or entity.domain != "button"
                or entity.unique_id == refresh_id
            ):
                continue
            if entity.unique_id not in current:
                registry.async_remove(entity.entity_id)
            elif current[entity.unique_id][1] is None and entity.device_id != hub.id:
                registry.async_update_entity(
                    entity.entity_id,
                    device_id=hub.id,
                    original_name=current[entity.unique_id][3],
                )
            elif entity.original_name != current[entity.unique_id][3]:
                registry.async_update_entity(
                    entity.entity_id, original_name=current[entity.unique_id][3]
                )
        for device in device_registry.async_entries_for_config_entry(devices, entry.entry_id):
            if device.id not in current_device_ids and device.config_entry_id == entry.entry_id:
                devices.async_remove_device(device.id)

        added = [
            InelsIrButton(coordinator, entry, unique_id, *values)
            for unique_id, values in current.items()
            if unique_id not in known
        ]
        known.clear()
        known.update(current)
        if added:
            async_add_entities(added)

    entry.async_on_unload(coordinator.async_add_listener(sync_catalog))
    async_add_entities([RefreshCatalogButton(coordinator, hub_info, refresh_id)])
    sync_catalog()


class RefreshCatalogButton(ButtonEntity):
    """Reload the catalog even after a previous refresh failed."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_translation_key = "refresh_catalog"
    _attr_icon = "mdi:refresh"

    def __init__(
        self, coordinator: GatewayCoordinator, device_info: DeviceInfo, unique_id: str
    ) -> None:
        self._coordinator = coordinator
        self._attr_device_info = device_info
        self._attr_unique_id = unique_id

    async def async_press(self) -> None:
        await self._coordinator.async_refresh()
        if not self._coordinator.last_update_success:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="catalog_refresh_failed"
            )


class InelsIrButton(CoordinatorEntity[GatewayCoordinator], ButtonEntity):
    """Transmit one gateway slot or invoke a gateway device action."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:remote"

    def __init__(
        self,
        coordinator: GatewayCoordinator,
        entry: ConfigEntry,
        unique_id: str,
        device_info: DeviceInfo,
        device_id: str | None,
        command_id: str,
        label: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._command_id = command_id
        self._slot = int(command_id) if device_id is None else None
        self._attr_device_info = device_info
        self._attr_unique_id = unique_id
        self._attr_name = label
        if device_id is None:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_visible_default = False

    @property
    def name(self) -> str:
        """Use the current gateway label, including after a refresh."""
        if self._device_id is not None:
            device = self.coordinator.data.devices.get(self._device_id)
            if device is not None:
                return device.actions.get(self._command_id, self._attr_name)
        return self._attr_name

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Show firmware metadata in the details of each named button."""
        if self._device_id is not None:
            device = self.coordinator.data.devices.get(self._device_id)
            if device is not None:
                return {
                    key: device.metadata[key]
                    for key in ("description", "device_type")
                    if key in device.metadata
                }
        return None

    def _still_configured(self) -> bool:
        catalog = self.coordinator.data
        if self._device_id is None:
            return self._slot in catalog.slots
        device = catalog.devices.get(self._device_id)
        return device is not None and self._command_id in device.actions

    async def async_press(self) -> None:
        try:
            async with self.coordinator.lock:
                if (
                    self._entry.state != ConfigEntryState.LOADED
                    or self._entry.runtime_data is not self.coordinator
                    or not self.coordinator.last_update_success
                    or not self._still_configured()
                ):
                    raise GatewayError("Gateway button is unavailable")
                async with gateway_session() as session:
                    if self._device_id is None:
                        await send_code(session, self.coordinator.origin, self._command_id)
                    else:
                        await send_action(
                            session, self.coordinator.origin, self._device_id, self._command_id
                        )
        except (ClientError, TimeoutError, GatewayError) as err:
            detail = str(err) if isinstance(err, GatewayError) else type(err).__name__
            raise HomeAssistantError(f"Could not send iNELS IR command ({detail})") from None
