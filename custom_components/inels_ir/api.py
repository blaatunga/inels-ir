"""HTTP transport and configuration validation for eLAN-IR-003."""

from asyncio import IncompleteReadError
from ipaddress import ip_address, ip_network
import json
import logging
import re
from uuid import uuid4

from aiohttp import (
    ClientError,
    ClientResponse,
    ClientSession,
    ClientTimeout,
    DummyCookieJar,
    TCPConnector,
)
from yarl import URL

DOMAIN = "inels_ir"

_LOGGER = logging.getLogger(__name__)
_LOCAL_NETWORKS = tuple(
    ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)
_MAX_JSON_BYTES = 8192


def gateway_session() -> ClientSession:
    """Isolate legacy traffic and avoid a retry on a reused connection."""
    return ClientSession(
        connector=TCPConnector(force_close=True),
        cookie_jar=DummyCookieJar(),
        auto_decompress=False,
        trust_env=False,
    )


def gateway_url(address: str) -> URL:
    """Normalize a hostname, IP address or HTTP origin."""
    address = address.strip()
    if any(ord(char) < 33 or ord(char) == 127 for char in address) or "\\" in address:
        raise ValueError("Invalid gateway address")
    if "://" not in address:
        address = f"http://{address}"
    url = URL(address)
    if (
        url.scheme != "http"
        or not url.host
        or url.raw_user is not None
        or url.raw_password is not None
        or "@" in address
        or "?" in address
        or "#" in address
        or url.path != "/"
        or url.query_string
        or url.fragment
        or not 1 <= url.port <= 65535
    ):
        raise ValueError("Enter an HTTP origin without credentials or a path")
    return url.origin()


def learning_origin(origin: URL) -> URL:
    """Only send administrator credentials directly to a private IP address."""
    try:
        address = ip_address(origin.host or "")
    except ValueError:
        raise GatewayError("Learning requires the gateway's private IP address") from None
    if "%" in str(address) or not any(address in network for network in _LOCAL_NETWORKS):
        raise GatewayError("Learning requires the gateway's private IP address")
    return URL.build(scheme="http", host=str(address), port=origin.port)


async def identify_gateway(session: ClientSession, origin: URL) -> str:
    """Read the model signature and normalized MAC from the local API."""
    origin = learning_origin(origin)
    async with session.get(
        origin.with_path("/api"), allow_redirects=False, timeout=ClientTimeout(total=3)
    ) as response:
        if response.status != 200:
            raise GatewayError("Could not identify the gateway")
        payload = await _read_json(response)
    info = payload.get("info") if isinstance(payload, dict) else None
    if not isinstance(info, dict) or not all(
        isinstance(info.get(key), str) and info[key]
        for key in ("ELAN-IR version", "API version", "MAC address")
    ):
        raise GatewayError("Unexpected gateway identity")
    mac = info["MAC address"].replace(":", "").lower()
    if not re.fullmatch(r"[0-9a-f]{12}", mac):
        raise GatewayError("Unexpected gateway MAC address")
    return mac


class GatewayError(Exception):
    """The gateway did not accept an IR request."""


async def _read_json(response: ClientResponse) -> object:
    """Decode the gateway's small JSON replies with a hard read limit."""
    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise GatewayError("Unexpected compressed gateway response")
    try:
        await response.content.readexactly(_MAX_JSON_BYTES + 1)
    except IncompleteReadError as err:
        try:
            return json.loads(err.partial)
        except (ValueError, RecursionError):
            raise GatewayError("Invalid gateway JSON") from None
    raise GatewayError("Gateway JSON response exceeds the size limit")


async def send_code(session: ClientSession, origin: URL, code: str) -> None:
    """Transmit a stored IR code using the vendor's HTTP endpoint."""
    if not re.fullmatch(r"[0-9]{1,10}", code):
        raise GatewayError("Invalid IR slot")
    url = origin.with_path(f"/api/ir/{code}")
    async with session.put(
        url, allow_redirects=False, timeout=ClientTimeout(total=5)
    ) as response:
        if not 200 <= response.status < 300:
            raise GatewayError(f"HTTP {response.status}")


async def _get_object(session: ClientSession, origin: URL, path: str) -> dict:
    async with session.get(
        origin.with_path(path), allow_redirects=False, timeout=ClientTimeout(total=5)
    ) as response:
        if response.status != 200:
            raise GatewayError(f"Gateway read failed (HTTP {response.status})")
        payload = await _read_json(response)
    if not isinstance(payload, dict):
        raise GatewayError("Unexpected gateway response")
    return payload


async def read_slots(session: ClientSession, origin: URL) -> tuple[int, ...]:
    payload = await _get_object(session, origin, "/api/ir")
    signals = payload.get("signals")
    if not isinstance(signals, list) or any(
        type(slot) is not int or not 1 <= slot <= 200 for slot in signals
    ):
        raise GatewayError("Unexpected IR slot list")
    return tuple(sorted(set(signals)))


def _device_path(device_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", device_id):
        raise GatewayError("Invalid gateway device ID")
    return f"/api/devices/{device_id}"


async def read_devices(session: ClientSession, origin: URL) -> dict[str, dict]:
    index = await _get_object(session, origin, "/api/devices/")
    if len(index) > 200:
        raise GatewayError("Gateway device list exceeds the supported size")
    devices = {}
    for device_id in index:
        device = await _get_object(session, origin, _device_path(device_id))
        info = device.get("device info")
        if not isinstance(info, dict) or not isinstance(info.get("product type"), str):
            raise GatewayError("Unexpected gateway device information")
        if info["product type"] == "IR":
            devices[device_id] = device
    return devices


async def send_action(
    session: ClientSession, origin: URL, device_id: str, action_id: str
) -> None:
    """Trigger the configured action, including its output and slot selection."""
    await _write_action(session, origin, "PUT", _device_path(device_id), {action_id: None})


async def _write_action(
    session: ClientSession, origin: URL, method: str, path: str, data: dict
) -> None:
    # Match the legacy web client, which sends JSON in a form-typed request.
    async with session.request(
        method,
        origin.with_path(path),
        data=json.dumps(data, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        allow_redirects=False,
        timeout=ClientTimeout(total=5),
    ) as response:
        if response.status not in (200, 201, 204):
            raise GatewayError(f"Gateway write failed (HTTP {response.status})")


async def learn_code(
    session: ClientSession,
    origin: URL,
    username: str,
    password: str,
    expected_mac: str,
    *,
    device_name: str = "",
    button_name: str = "",
    ir_output: int = 1,
) -> str:
    """Learn a free slot and optionally save its button on the gateway."""
    origin = learning_origin(origin)
    if await identify_gateway(session, origin) != expected_mac:
        raise GatewayError("Gateway identity changed")
    request_options = {
        "allow_redirects": False,
        "timeout": ClientTimeout(total=5),
    }
    async with session.post(
        origin.with_path("/login"),
        data={"name": username, "key": password},
        **request_options,
    ) as response:
        if response.status != 201:
            raise GatewayError(f"Administrator login failed (HTTP {response.status})")

    try:
        device_id = None
        existing = False
        if device_name:
            devices = await read_devices(session, origin)
            matches = [
                key for key, device in devices.items()
                if device["device info"].get("label") == device_name
            ]
            if len(matches) > 1:
                raise GatewayError("More than one gateway device has that name")
            device_id = matches[0] if matches else f"ha-{uuid4().hex[:12]}"
            existing = bool(matches)
            if existing:
                _check_new_action(devices[device_id], button_name)

        code = await _record_code(session, origin)
        if device_id:
            try:
                await _save_button(
                    session, origin, device_id, device_name, button_name, code, ir_output,
                    existing=existing,
                )
            except (ClientError, TimeoutError, ValueError, GatewayError):
                raise GatewayError(
                    f"IR slot {code} was learned. Check the gateway for the button before retrying."
                ) from None
        return code
    finally:
        try:
            async with session.post(origin.with_path("/logout"), **request_options) as response:
                if response.status != 200:
                    _LOGGER.warning("iNELS IR logout returned HTTP %s", response.status)
        except (ClientError, TimeoutError):
            _LOGGER.warning("Could not close the iNELS IR administrator session")


def device_actions(device: dict) -> dict[str, str]:
    """Read named primary and secondary actions without interpreting the IR sequence."""
    primary = device.get("actions info", {})
    secondary = device.get("secondary actions", [])
    if not isinstance(primary, dict) or not isinstance(secondary, list):
        raise GatewayError("Unexpected gateway action list")
    actions = {key: key for key in primary}
    for group in secondary:
        if not isinstance(group, dict):
            raise GatewayError("Unexpected gateway secondary action")
        for key, action in group.items():
            if not isinstance(action, dict):
                raise GatewayError("Unexpected gateway secondary action")
            label = action.get("label")
            actions[key] = label if isinstance(label, str) and label.strip() else key
    return actions


def _check_new_action(device: dict, button_name: str) -> None:
    actions = device_actions(device)
    if button_name in actions or button_name in actions.values():
        raise GatewayError("That button already exists on the gateway")


async def _save_button(
    session: ClientSession, origin: URL, device_id: str, device_name: str,
    button_name: str, code: str, ir_output: int,
    *, existing: bool,
) -> None:
    devices = await read_devices(session, origin)
    if existing != (device_id in devices):
        raise GatewayError("Gateway device changed during recording")
    if device_id in devices:
        device = devices[device_id]
        if device["device info"].get("label") != device_name:
            raise GatewayError("Gateway device changed during recording")
    else:
        if any(d["device info"].get("label") == device_name for d in devices.values()):
            raise GatewayError("Gateway device changed during recording")
        types = await _get_object(session, origin, "/api/configuration/device_types")
        if not types:
            raise GatewayError("Gateway returned no device types")
        device = {
            "device info": {
                "type": "appliance" if "appliance" in types else next(iter(types)),
                "product type": "IR",
                "label": device_name,
            },
            "IR product info": {"product": "", "vendor": "", "description": ""},
            "secondary actions": [],
        }
    _check_new_action(device, button_name)
    device["id"] = device_id
    device.setdefault("actions info", {})[button_name] = {
        "type": None, "ir codes": [int(code)], "ir LED": ir_output,
    }
    await _write_action(session, origin, "POST", "/api/devices/", device)
    saved = await _get_object(session, origin, _device_path(device_id))
    actions = saved.get("actions info")
    if not isinstance(actions, dict) or actions.get(button_name) != device["actions info"][button_name]:
        raise GatewayError("Gateway did not confirm the saved button")


async def _record_code(session: ClientSession, origin: URL) -> str:
    occupied = set(await read_slots(session, origin))
    slot = next((slot for slot in range(1, 201) if slot not in occupied), None)
    if slot is None:
        raise GatewayError("No free IR slots")

    async with session.post(
        origin.with_path(f"/api/ir/{slot}"),
        allow_redirects=False,
        timeout=ClientTimeout(total=60),
    ) as response:
        if response.status not in (200, 201):
            raise GatewayError(f"IR recording failed (HTTP {response.status})")
        payload = await _read_json(response)
    recorded = payload.get("ir code") if isinstance(payload, dict) else None
    if type(recorded) not in (str, int) or str(recorded) != str(slot):
        raise GatewayError(f"Gateway did not confirm IR recording in slot {slot}")
    return str(slot)
