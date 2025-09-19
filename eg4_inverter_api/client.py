"""EG4 Inverter API Client."""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlencode

import aiohttp
from aiohttp import ClientTimeout

from .exceptions import EG4APIError, EG4AuthError, EG4ConnectionError, EG4DeviceError

_LOGGER = logging.getLogger(__name__)


class EG4InverterAPI:
    """EG4 Inverter API Client."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        username: str,
        password: str,
        *,
        base_url: str = "https://monitor.eg4electronics.com",
        verify_ssl: bool = True,
        timeout: int = 30
    ):
        """Initialize the EG4 Inverter API client."""
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.timeout = ClientTimeout(total=timeout)

        self._session: Optional[aiohttp.ClientSession] = None
        self._session_id: Optional[str] = None
        self._session_expires: Optional[datetime] = None
        self._plants: Optional[List[Dict[str, Any]]] = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=self.verify_ssl)
            self._session = aiohttp.ClientSession(
                connector=connector, timeout=self.timeout
            )
        return self._session

    async def close(self):
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _ensure_authenticated(self):
        """Ensure we have a valid authenticated session."""
        if (
            self._session_id is None
            or self._session_expires is None
            or datetime.now() >= self._session_expires
        ):
            await self.login()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        authenticated: bool = True,
    ) -> Dict[str, Any]:
        """Make an HTTP request to the API."""
        if authenticated:
            await self._ensure_authenticated()

        session = await self._get_session()
        url = urljoin(self.base_url, endpoint)

        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; EG4InverterAPI/1.0)",
        }

        if authenticated and self._session_id:
            headers["Cookie"] = f"JSESSIONID={self._session_id}"

        # URL-encode the data for form submission
        encoded_data = None
        if data:
            encoded_data = urlencode(data)

        try:
            _LOGGER.debug("Making %s request to %s with data: %s", method, url, data)
            async with session.request(
                method, url, headers=headers, data=encoded_data
            ) as response:
                if response.content_type == "application/json":
                    result = await response.json()
                else:
                    text = await response.text()
                    try:
                        result = json.loads(text)
                    except json.JSONDecodeError:
                        result = {"text": text}

                # Handle authentication errors
                if response.status == 401:
                    raise EG4AuthError("Authentication failed")

                # Handle API errors
                if not response.ok:
                    raise EG4ConnectionError(f"HTTP {response.status}: {result}")

                # Check for API error responses
                if isinstance(result, dict) and result.get("success") is False:
                    error_msg = result.get("message", "Unknown API error")
                    if "login" in error_msg.lower() or "auth" in error_msg.lower():
                        raise EG4AuthError(error_msg)
                    raise EG4APIError(error_msg)

                return result

        except aiohttp.ClientError as e:
            raise EG4ConnectionError(f"Connection error: {e}") from e

    async def login(self) -> Dict[str, Any]:
        """Authenticate with the EG4 API."""
        data = {
            "account": self.username,
            "password": self.password,
        }

        try:
            result = await self._make_request(
                "POST", "/WManage/api/login", data=data, authenticated=False
            )

            # Extract session ID from cookies
            session = await self._get_session()
            # pylint: disable=protected-access
            if hasattr(session, "_cookie_jar") and session._cookie_jar:
                for cookie in session._cookie_jar:
                    if cookie.key == "JSESSIONID":
                        self._session_id = cookie.value
                        break

            if not self._session_id:
                # Try to extract from response headers if available
                # This is a fallback method
                pass

            # Set session expiry (2 hours as per documentation)
            self._session_expires = datetime.now() + timedelta(hours=2)

            _LOGGER.info("Successfully authenticated with EG4 API")
            return result

        except Exception as e:
            _LOGGER.error("Login failed: %s", e)
            raise EG4AuthError(f"Login failed: {e}") from e

    async def get_plants(self) -> List[Dict[str, Any]]:
        """Get list of plants/stations."""
        data = {
            "sort": "createDate",
            "order": "desc",
            "searchText": "",
        }

        result = await self._make_request(
            "POST", "/WManage/web/config/plant/list/viewer", data=data
        )

        if isinstance(result, dict) and "rows" in result:
            self._plants = result["rows"]
            return self._plants

        raise EG4APIError("Invalid plants response format")

    async def get_parallel_group_details(self, serial_number: str) -> Dict[str, Any]:
        """Get parallel group details for a device."""
        data = {"serialNum": serial_number}

        return await self._make_request(
            "POST", "/WManage/api/inverterOverview/getParallelGroupDetails", data=data
        )

    async def get_inverter_overview(self, plant_id: str) -> Dict[str, Any]:
        """Get inverter overview for a plant."""
        data = {"plantId": plant_id, "page": 1}

        return await self._make_request(
            "POST", "/WManage/api/inverterOverview/list", data=data
        )

    async def get_inverter_runtime(self, serial_number: str) -> Dict[str, Any]:
        """Get inverter runtime data."""
        data = {"serialNum": serial_number}

        return await self._make_request(
            "POST", "/WManage/api/inverter/getInverterRuntime", data=data
        )

    async def get_inverter_energy_info(self, serial_number: str) -> Dict[str, Any]:
        """Get inverter energy information."""
        data = {"serialNum": serial_number}

        return await self._make_request(
            "POST", "/WManage/api/inverter/getInverterEnergyInfo", data=data
        )

    async def get_inverter_energy_info_parallel(
        self, serial_number: str
    ) -> Dict[str, Any]:
        """Get parallel inverter energy information."""
        data = {"serialNum": serial_number}

        return await self._make_request(
            "POST", "/WManage/api/inverter/getInverterEnergyInfoParallel", data=data
        )

    async def get_battery_info(self, serial_number: str) -> Dict[str, Any]:
        """Get battery information for an inverter."""
        data = {"serialNum": serial_number}

        return await self._make_request(
            "POST", "/WManage/api/battery/getBatteryInfo", data=data
        )

    async def get_midbox_runtime(self, serial_number: str) -> Dict[str, Any]:
        """Get MidBox (GridBOSS) runtime data."""
        data = {"serialNum": serial_number}

        try:
            return await self._make_request(
                "POST", "/WManage/api/midbox/getMidboxRuntime", data=data
            )
        except EG4APIError as e:
            if "DEVICE_ERROR_UNSUPPORT_DEVICE_TYPE" in str(e):
                raise EG4DeviceError(
                    f"Device {serial_number} does not support MidBox operations"
                ) from e
            raise

    # Convenience methods for multi-device operations

    async def get_all_device_data(self, plant_id: str) -> Dict[str, Any]:
        """Get comprehensive data for all devices in a plant."""
        # Use device information from login response instead of broken discovery endpoints
        serial_numbers = set()
        gridboss_serials = set()
        device_info = {}

        # Get fresh login data to access device information
        login_data = await self.login()

        # Extract devices from login response plants array
        for plant in login_data.get("plants", []):
            if str(plant.get("plantId")) == str(plant_id):
                for device in plant.get("inverters", []):
                    serial = device.get("serialNum")
                    if serial:
                        serial_numbers.add(serial)
                        device_info[serial] = device

                        # Check if this is a GridBOSS device
                        model = device.get("deviceTypeText4APP", "").lower()
                        if "gridboss" in model or "grid boss" in model:
                            gridboss_serials.add(serial)

                # Also extract parallel group information
                parallel_groups = plant.get("parallelGroups", [])
                break

        _LOGGER.info(
            "Found %d devices for plant %s: %s",
            len(serial_numbers), plant_id, list(serial_numbers)
        )
        _LOGGER.info("GridBOSS devices: %s", list(gridboss_serials))

        # Try to get additional device discovery data (but don't fail if it doesn't work)
        parallel_groups_data = None
        inverter_overview_data = None

        # Disable problematic discovery endpoints - core functionality works without them
        parallel_groups_data = None
        inverter_overview_data = None
        _LOGGER.debug(
            "Skipping parallel groups and inverter overview discovery endpoints "
            "(not essential for core functionality)"
        )

        # Fetch data for all devices concurrently
        tasks = []

        for serial in serial_numbers:
            if serial in gridboss_serials:
                # GridBOSS device - get midbox runtime
                tasks.append(self._get_gridboss_data(serial))
            else:
                # Standard inverter - get full data set
                tasks.append(self._get_inverter_data(serial))

        # Execute all tasks concurrently
        device_data = await asyncio.gather(*tasks, return_exceptions=True)

        # Try to get parallel group energy data using any available serial
        parallel_energy_data = None
        if serial_numbers:
            try:
                # Use the first available serial number to get parallel group energy data
                first_serial = next(iter(serial_numbers))
                parallel_energy_data = await self.get_inverter_energy_info_parallel(
                    first_serial
                )
                _LOGGER.debug("Successfully retrieved parallel group energy data")
            except Exception as e:
                _LOGGER.warning("Failed to get parallel group energy data: %s", e)

        # Organize results
        result = {
            "parallel_groups": parallel_groups_data,
            "parallel_groups_info": parallel_groups,  # From login response
            "parallel_energy": parallel_energy_data,
            "inverter_overview": inverter_overview_data,
            "device_info": device_info,  # Include device info from login
            "devices": {},
        }

        for i, serial in enumerate(serial_numbers):
            data = device_data[i]
            if isinstance(data, Exception):
                _LOGGER.error("Failed to get data for device %s: %s", serial, data)
                result["devices"][serial] = {"error": str(data)}
            else:
                result["devices"][serial] = data

        return result

    async def _get_inverter_data(self, serial_number: str) -> Dict[str, Any]:
        """Get comprehensive data for a standard inverter."""
        tasks = [
            self.get_inverter_runtime(serial_number),
            self.get_inverter_energy_info(serial_number),
            self.get_battery_info(serial_number),
        ]

        try:
            runtime, energy, battery = await asyncio.gather(*tasks)
            return {
                "serial": serial_number,
                "type": "inverter",
                "runtime": runtime,
                "energy": energy,
                "battery": battery,
            }
        except Exception as e:
            _LOGGER.error("Failed to get inverter data for %s: %s", serial_number, e)
            raise

    async def _get_gridboss_data(self, serial_number: str) -> Dict[str, Any]:
        """Get data for a GridBOSS device."""
        try:
            midbox_data = await self.get_midbox_runtime(serial_number)
            return {
                "serial": serial_number,
                "type": "gridboss",
                "midbox": midbox_data,
            }
        except Exception as e:
            _LOGGER.error("Failed to get GridBOSS data for %s: %s", serial_number, e)
            raise

    async def read_parameters(
        self, inverter_sn: str, start_register: int = 0, point_number: int = 127
    ) -> Dict[str, Any]:
        """Read parameters from an inverter using the remote read endpoint.

        Args:
            inverter_sn: The inverter serial number
            start_register: Starting register address (default: 0)
            point_number: Number of registers to read (default: 127)

        Returns:
            Dict containing the parameter read response
        """
        endpoint = "/WManage/web/maintain/remoteRead/read"
        data = {
            "inverterSn": inverter_sn,
            "startRegister": start_register,
            "pointNumber": point_number,
        }

        _LOGGER.debug(
            "Reading parameters from inverter %s: start_register=%s, point_number=%s",
            inverter_sn,
            start_register,
            point_number,
        )

        try:
            response = await self._make_request("POST", endpoint, data)
            return response
        except Exception as e:
            _LOGGER.error(
                "Failed to read parameters from inverter %s: %s", inverter_sn, e
            )
            raise EG4APIError(f"Parameter read failed for {inverter_sn}: {e}") from e

    async def write_parameter(  # pylint: disable=too-many-arguments
        self,
        inverter_sn: str,
        hold_param: str,
        value_text: str,
        *,
        client_type: str = "WEB",
        remote_set_type: str = "NORMAL"
    ) -> Dict[str, Any]:
        """Write a parameter to an inverter using the remote write endpoint.

        Args:
            inverter_sn: The inverter serial number
            hold_param: The parameter name to write (e.g., "HOLD_SYSTEM_CHARGE_SOC_LIMIT")
            value_text: The value to write as string
            client_type: Client type (default: "WEB")
            remote_set_type: Remote set type (default: "NORMAL")

        Returns:
            Dict containing the parameter write response
        """
        endpoint = "/WManage/web/maintain/remoteSet/write"
        data = {
            "inverterSn": inverter_sn,
            "holdParam": hold_param,
            "valueText": value_text,
            "clientType": client_type,
            "remoteSetType": remote_set_type,
        }

        _LOGGER.debug(
            "Writing parameter to inverter %s: %s=%s",
            inverter_sn,
            hold_param,
            value_text,
        )

        try:
            response = await self._make_request("POST", endpoint, data)
            return response
        except Exception as e:
            _LOGGER.error(
                "Failed to write parameter to inverter %s: %s", inverter_sn, e
            )
            raise EG4APIError(f"Parameter write failed for {inverter_sn}: {e}") from e

    async def start_quick_charge(self, serial_number: str) -> Dict[str, Any]:
        """Start quick charge for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the quick charge start response
        """
        data = {
            "inverterSn": serial_number,
            "clientType": "WEB"
        }

        _LOGGER.debug("Starting quick charge for inverter %s", serial_number)

        try:
            response = await self._make_request(
                "POST", "/WManage/web/config/quickCharge/start", data
            )
            _LOGGER.info("Successfully started quick charge for inverter %s", serial_number)
            return response
        except Exception as e:
            _LOGGER.error("Failed to start quick charge for inverter %s: %s", serial_number, e)
            raise EG4APIError(f"Quick charge start failed for {serial_number}: {e}") from e

    async def stop_quick_charge(self, serial_number: str) -> Dict[str, Any]:
        """Stop quick charge for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the quick charge stop response
        """
        data = {
            "inverterSn": serial_number,
            "clientType": "WEB"
        }

        _LOGGER.debug("Stopping quick charge for inverter %s", serial_number)

        try:
            response = await self._make_request(
                "POST", "/WManage/web/config/quickCharge/stop", data
            )
            _LOGGER.info("Successfully stopped quick charge for inverter %s", serial_number)
            return response
        except Exception as e:
            _LOGGER.error("Failed to stop quick charge for inverter %s: %s", serial_number, e)
            raise EG4APIError(f"Quick charge stop failed for {serial_number}: {e}") from e

    async def get_quick_charge_status(self, serial_number: str) -> Dict[str, Any]:
        """Get current quick charge status for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the quick charge status
        """
        data = {"inverterSn": serial_number}

        _LOGGER.debug("Getting quick charge status for inverter %s", serial_number)

        try:
            response = await self._make_request(
                "POST", "/WManage/web/config/quickCharge/getStatusInfo", data
            )
            return response
        except Exception as e:
            _LOGGER.error("Failed to get quick charge status for inverter %s: %s", serial_number, e)
            raise EG4APIError(f"Quick charge status check failed for {serial_number}: {e}") from e

    async def enable_battery_backup(self, serial_number: str) -> Dict[str, Any]:
        """Enable battery backup (EPS) for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the battery backup enable response
        """
        data = {
            "inverterSn": serial_number,
            "functionParam": "FUNC_EPS_EN",
            "enable": "true",
            "clientType": "WEB",
            "remoteSetType": "NORMAL"
        }

        _LOGGER.debug("Enabling battery backup for inverter %s", serial_number)

        try:
            response = await self._make_request(
                "POST", "/WManage/web/maintain/remoteSet/functionControl", data
            )
            _LOGGER.info("Successfully enabled battery backup for inverter %s", serial_number)
            return response
        except Exception as e:
            _LOGGER.error("Failed to enable battery backup for inverter %s: %s", serial_number, e)
            raise EG4APIError(f"Battery backup enable failed for {serial_number}: {e}") from e

    async def disable_battery_backup(self, serial_number: str) -> Dict[str, Any]:
        """Disable battery backup (EPS) for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the battery backup disable response
        """
        data = {
            "inverterSn": serial_number,
            "functionParam": "FUNC_EPS_EN",
            "enable": "false",
            "clientType": "WEB",
            "remoteSetType": "NORMAL"
        }

        _LOGGER.debug("Disabling battery backup for inverter %s", serial_number)

        try:
            response = await self._make_request(
                "POST", "/WManage/web/maintain/remoteSet/functionControl", data
            )
            _LOGGER.info("Successfully disabled battery backup for inverter %s", serial_number)
            return response
        except Exception as e:
            _LOGGER.error("Failed to disable battery backup for inverter %s: %s", serial_number, e)
            raise EG4APIError(f"Battery backup disable failed for {serial_number}: {e}") from e

    def get_battery_backup_status(self, parameters: Dict[str, Any]) -> bool:
        """Extract battery backup status from parameter data.

        Args:
            parameters: Dictionary containing device parameters

        Returns:
            True if battery backup is enabled, False otherwise
        """
        return parameters.get("FUNC_EPS_EN", False)
