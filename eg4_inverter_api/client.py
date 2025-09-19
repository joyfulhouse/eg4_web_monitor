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

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # pylint: disable=unused-argument
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

    # Endpoint constants
    _ENDPOINTS = {
        "parallel_group_details": "/WManage/api/inverterOverview/getParallelGroupDetails",
        "inverter_overview": "/WManage/api/inverterOverview/list",
        "inverter_runtime": "/WManage/api/inverter/getInverterRuntime",
        "inverter_energy": "/WManage/api/inverter/getInverterEnergyInfo",
        "inverter_energy_parallel": "/WManage/api/inverter/getInverterEnergyInfoParallel",
        "battery_info": "/WManage/api/battery/getBatteryInfo",
        "midbox_runtime": "/WManage/api/midbox/getMidboxRuntime",
        "quick_charge_status": "/WManage/web/config/quickCharge/getStatusInfo",
        "parameter_read": "/WManage/web/maintain/remoteRead/read",
        "parameter_write": "/WManage/web/maintain/remoteSet/write",
        "function_control": "/WManage/web/maintain/remoteSet/functionControl",
    }

    async def _request_with_serial(
        self, 
        endpoint_key: str, 
        serial_number: str,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make a request with serialNum parameter.
        
        Args:
            endpoint_key: Key to look up endpoint in _ENDPOINTS
            serial_number: The device serial number
            extra_data: Additional data to include in request
            
        Returns:
            Dict containing the API response
        """
        data = {"serialNum": serial_number}
        if extra_data:
            data.update(extra_data)
            
        return await self._make_request("POST", self._ENDPOINTS[endpoint_key], data=data)

    async def get_parallel_group_details(self, serial_number: str) -> Dict[str, Any]:
        """Get parallel group details for a device."""
        return await self._request_with_serial("parallel_group_details", serial_number)

    async def get_inverter_overview(self, plant_id: str) -> Dict[str, Any]:
        """Get inverter overview for a plant."""
        data = {"plantId": plant_id, "page": 1}
        return await self._make_request("POST", self._ENDPOINTS["inverter_overview"], data=data)

    async def get_inverter_runtime(self, serial_number: str) -> Dict[str, Any]:
        """Get inverter runtime data."""
        return await self._request_with_serial("inverter_runtime", serial_number)

    async def get_inverter_energy_info(self, serial_number: str) -> Dict[str, Any]:
        """Get inverter energy information."""
        return await self._request_with_serial("inverter_energy", serial_number)

    async def get_inverter_energy_info_parallel(self, serial_number: str) -> Dict[str, Any]:
        """Get parallel inverter energy information."""
        return await self._request_with_serial("inverter_energy_parallel", serial_number)

    async def get_battery_info(self, serial_number: str) -> Dict[str, Any]:
        """Get battery information for an inverter."""
        return await self._request_with_serial("battery_info", serial_number)

    async def get_midbox_runtime(self, serial_number: str) -> Dict[str, Any]:
        """Get MidBox (GridBOSS) runtime data."""
        try:
            return await self._request_with_serial("midbox_runtime", serial_number)
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

        # Skip problematic discovery endpoints - core functionality works without them
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
            "parallel_groups": None,  # Discovery endpoints disabled
            "parallel_groups_info": parallel_groups,  # From login response
            "parallel_energy": parallel_energy_data,
            "inverter_overview": None,  # Discovery endpoints disabled
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

    async def _request_with_inverter_sn(
        self,
        endpoint_key: Optional[str],
        inverter_sn: str,
        operation: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Make a request with inverterSn parameter and standardized error handling.
        
        Args:
            endpoint_key: Key to look up endpoint in _ENDPOINTS (None for custom endpoint)
            inverter_sn: The inverter serial number
            operation: Description of operation for logging/errors
            **kwargs: Additional data to include in request
                     _custom_endpoint: Use this endpoint instead of looking up endpoint_key
            
        Returns:
            Dict containing the API response
        """
        # Extract custom endpoint if provided
        custom_endpoint = kwargs.pop("_custom_endpoint", None)
        data = {"inverterSn": inverter_sn, **kwargs}
        
        # Determine endpoint to use
        if custom_endpoint:
            endpoint = custom_endpoint
        elif endpoint_key:
            endpoint = self._ENDPOINTS[endpoint_key]
        else:
            raise ValueError("Either endpoint_key or _custom_endpoint must be provided")
        
        _LOGGER.debug("%s for inverter %s", operation.capitalize(), inverter_sn)
        
        try:
            response = await self._make_request("POST", endpoint, data)
            _LOGGER.debug("Successfully completed %s for inverter %s", operation, inverter_sn)
            return response
        except Exception as e:
            _LOGGER.error("Failed %s for inverter %s: %s", operation, inverter_sn, e)
            raise EG4APIError(f"{operation.capitalize()} failed for {inverter_sn}: {e}") from e

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
        return await self._request_with_inverter_sn(
            "parameter_read",
            inverter_sn,
            f"parameter read (reg {start_register}, count {point_number})",
            startRegister=start_register,
            pointNumber=point_number
        )

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
        return await self._request_with_inverter_sn(
            "parameter_write",
            inverter_sn,
            f"parameter write ({hold_param}={value_text})",
            holdParam=hold_param,
            valueText=value_text,
            clientType=client_type,
            remoteSetType=remote_set_type
        )

    async def control_quick_charge(
        self,
        serial_number: str,
        start: bool,
        *,
        client_type: str = "WEB"
    ) -> Dict[str, Any]:
        """Control quick charge for specified inverter.

        Args:
            serial_number: The inverter serial number
            start: True to start, False to stop
            client_type: Client type (default: "WEB")

        Returns:
            Dict containing the quick charge control response
        """
        action = "start" if start else "stop"
        endpoint = f"/WManage/web/config/quickCharge/{action}"
        
        return await self._request_with_inverter_sn(
            None,  # Custom endpoint, not in _ENDPOINTS
            serial_number,
            f"quick charge {action}",
            clientType=client_type,
            _custom_endpoint=endpoint
        )

    async def start_quick_charge(self, serial_number: str) -> Dict[str, Any]:
        """Start quick charge for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the quick charge start response
        """
        return await self.control_quick_charge(serial_number, True)

    async def stop_quick_charge(self, serial_number: str) -> Dict[str, Any]:
        """Stop quick charge for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the quick charge stop response
        """
        return await self.control_quick_charge(serial_number, False)

    async def get_quick_charge_status(self, serial_number: str) -> Dict[str, Any]:
        """Get current quick charge status for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the quick charge status
        """
        return await self._request_with_inverter_sn(
            "quick_charge_status",
            serial_number,
            "quick charge status check"
        )

    async def control_function_parameter(  # pylint: disable=too-many-arguments
        self,
        serial_number: str,
        function_param: str,
        enable: bool,
        *,
        client_type: str = "WEB",
        remote_set_type: str = "NORMAL"
    ) -> Dict[str, Any]:
        """Control a function parameter for specified inverter.

        Args:
            serial_number: The inverter serial number
            function_param: The function parameter name (e.g., "FUNC_EPS_EN")
            enable: True to enable, False to disable
            client_type: Client type (default: "WEB")
            remote_set_type: Remote set type (default: "NORMAL")

        Returns:
            Dict containing the function control response
        """
        action = "enable" if enable else "disable"
        return await self._request_with_inverter_sn(
            "function_control",
            serial_number,
            f"{action} function parameter {function_param}",
            functionParam=function_param,
            enable="true" if enable else "false",
            clientType=client_type,
            remoteSetType=remote_set_type
        )

    async def enable_battery_backup(self, serial_number: str) -> Dict[str, Any]:
        """Enable battery backup (EPS) for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the battery backup enable response
        """
        return await self.control_function_parameter(serial_number, "FUNC_EPS_EN", True)

    async def disable_battery_backup(self, serial_number: str) -> Dict[str, Any]:
        """Disable battery backup (EPS) for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the battery backup disable response
        """
        return await self.control_function_parameter(serial_number, "FUNC_EPS_EN", False)

    def get_battery_backup_status(self, parameters: Dict[str, Any]) -> bool:
        """Extract battery backup status from parameter data.

        Args:
            parameters: Dictionary containing device parameters

        Returns:
            True if battery backup is enabled, False otherwise
        """
        return parameters.get("FUNC_EPS_EN", False)
