"""Read the gateway catalog as a single snapshot."""

from asyncio import Lock, timeout
from dataclasses import dataclass
import logging

from aiohttp import ClientError
from yarl import URL

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    DOMAIN, GatewayError, device_actions, device_metadata, device_name_from_record,
    gateway_session, identify_gateway,
)
from .api import read_devices, read_slots

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteControl:
    """A remote configured on the gateway."""

    name: str
    actions: dict[str, str]
    metadata: dict[str, str]


@dataclass(frozen=True)
class Catalog:
    """Slots and device actions read from the gateway."""

    slots: tuple[int, ...]
    devices: dict[str, RemoteControl]


class GatewayCoordinator(DataUpdateCoordinator[Catalog]):
    """Reconcile Home Assistant with the gateway catalog on demand."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            always_update=False,
        )
        self.origin = URL(entry.data[CONF_HOST])
        self.mac = entry.data.get(CONF_MAC)
        self.lock = Lock()

    async def _async_update_data(self) -> Catalog:
        try:
            async with self.lock, timeout(25), gateway_session() as session:
                if self.mac and await identify_gateway(session, self.origin) != self.mac:
                    raise GatewayError("Gateway identity changed")
                slots = await read_slots(session, self.origin)
                records = await read_devices(session, self.origin)
                devices = {
                    device_id: RemoteControl(
                        device_name_from_record(record, device_id),
                        device_actions(record),
                        device_metadata(record),
                    )
                    for device_id, record in records.items()
                }
                return Catalog(slots, devices)
        except (ClientError, TimeoutError, ValueError, GatewayError) as err:
            detail = str(err) if isinstance(err, GatewayError) else type(err).__name__
            raise UpdateFailed(detail) from None
