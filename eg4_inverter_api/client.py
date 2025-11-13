"""EG4 Inverter API Client."""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlencode

import aiohttp
from aiohttp import ClientTimeout

from .exceptions import EG4APIError, EG4AuthError, EG4ConnectionError, EG4DeviceError

_LOGGER = logging.getLogger(__name__)


class EG4InverterAPI:  # pylint: disable=too-many-public-methods
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

        # Device discovery cache to avoid repeated login calls
        self._device_cache: Dict[str, Dict[str, Any]] = {}
        self._device_cache_expires: Optional[datetime] = None
        self._device_cache_ttl = timedelta(minutes=15)  # Cache device info for 15 minutes

        # Response cache for API endpoints with TTL
        self._response_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl_config = {
            # Static data - cache longer
            "battery_info": timedelta(minutes=5),      # Battery info changes slowly

            # Control parameters - cache medium term for responsiveness vs performance
            "parameter_read": timedelta(minutes=2),    # Parameters change with user controls
            "quick_charge_status": timedelta(minutes=1), # Status changes during operations

            # Dynamic data - cache shorter
            "inverter_runtime": timedelta(seconds=20), # Runtime data changes frequently
            "inverter_energy": timedelta(seconds=20),   # Energy data changes moderately
            "midbox_runtime": timedelta(seconds=20),   # GridBOSS runtime changes frequently
        }

        # Backoff configuration for rate limiting
        self._backoff_config = {
            "base_delay": 1.0,     # Base delay in seconds
            "max_delay": 60.0,     # Maximum delay in seconds
            "exponential_factor": 2.0,  # Exponential backoff factor
            "jitter": 0.1          # Random jitter to prevent thundering herd
        }
        self._current_backoff_delay = 0.0
        self._last_request_time: Optional[datetime] = None
        self._consecutive_errors = 0

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

    async def _apply_backoff(self) -> None:
        """Apply incremental backoff delay before API requests."""
        if self._current_backoff_delay > 0:
            # Add jitter to prevent thundering herd
            jitter = random.uniform(0, self._backoff_config["jitter"])
            delay = self._current_backoff_delay + jitter
            _LOGGER.debug("Applying backoff delay: %.2f seconds", delay)
            await asyncio.sleep(delay)

    def _handle_request_success(self) -> None:
        """Reset backoff on successful request."""
        if self._consecutive_errors > 0:
            _LOGGER.debug(
                "Request successful, resetting backoff after %d errors", self._consecutive_errors
            )
        self._consecutive_errors = 0
        self._current_backoff_delay = 0.0

    def _handle_request_error(self) -> None:
        """Increase backoff delay on request error."""
        self._consecutive_errors += 1
        base_delay = self._backoff_config["base_delay"]
        max_delay = self._backoff_config["max_delay"]
        factor = self._backoff_config["exponential_factor"]

        # Calculate exponential backoff with cap
        self._current_backoff_delay = min(
            base_delay * (factor ** (self._consecutive_errors - 1)),
            max_delay
        )

        _LOGGER.warning(
            "API request error #%d, next backoff delay: %.2f seconds",
            self._consecutive_errors, self._current_backoff_delay
        )

    def _get_cache_key(self, endpoint_key: str, **params) -> str:
        """Generate a cache key for an endpoint and parameters."""
        # Sort parameters for consistent cache keys
        param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{endpoint_key}:{param_str}"

    def _is_cache_valid(self, cache_key: str, endpoint_key: str) -> bool:
        """Check if cached response is still valid."""
        if cache_key not in self._response_cache:
            return False

        cache_entry = self._response_cache[cache_key]
        cache_time = cache_entry.get("timestamp")
        if not cache_time:
            return False

        ttl = self._cache_ttl_config.get(endpoint_key, timedelta(seconds=30))
        return datetime.now() < cache_time + ttl

    def _cache_response(self, cache_key: str, response: Dict[str, Any]) -> None:
        """Cache a response with timestamp."""
        self._response_cache[cache_key] = {
            "timestamp": datetime.now(),
            "response": response
        }

        # Cleanup old cache entries (keep last 100 entries)
        if len(self._response_cache) > 100:
            # Remove oldest entries
            sorted_entries = sorted(
                self._response_cache.items(),
                key=lambda x: x[1]["timestamp"]
            )
            for old_key, _ in sorted_entries[:-80]:  # Keep 80 most recent
                del self._response_cache[old_key]

    async def _ensure_authenticated(self):
        """Ensure we have a valid authenticated session."""
        if (
            self._session_id is None
            or self._session_expires is None
            or datetime.now() >= self._session_expires
        ):
            await self.login()

    async def _make_request(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        authenticated: bool = True,
        retry_count: int = 0,
    ) -> Dict[str, Any]:
        """Make an HTTP request to the API with authentication retry logic."""
        # Apply backoff delay before making the request
        await self._apply_backoff()

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
                    self._handle_request_error()  # Track error for backoff
                    raise EG4ConnectionError(f"HTTP {response.status}: {result}")

                # Check for API error responses
                if isinstance(result, dict) and result.get("success") is False:
                    error_msg = result.get("message", "Unknown API error")
                    # Add more context for debugging
                    detailed_error = f"{error_msg} (Response: {result})"
                    if "login" in error_msg.lower() or "auth" in error_msg.lower():
                        raise EG4AuthError(detailed_error)
                    self._handle_request_error()  # Track error for backoff
                    raise EG4APIError(detailed_error)

                # Request was successful
                self._handle_request_success()
                return result

        except EG4AuthError as e:
            # If authentication failed and we haven't retried yet, try re-authenticating
            if authenticated and retry_count == 0:
                _LOGGER.warning("Authentication failed, attempting re-authentication: %s", e)
                # Clear current session and force re-authentication
                self._session_id = None
                self._session_expires = None
                # Retry the request once with fresh authentication
                return await self._make_request(
                    method, endpoint, data, authenticated, retry_count + 1
                )
            # Re-authentication failed or this was already a retry
            self._handle_request_error()  # Track error for backoff
            _LOGGER.error("Re-authentication failed: %s", e)
            raise
        except aiohttp.ClientError as e:
            self._handle_request_error()  # Track error for backoff
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

            # Clear parameter cache on new login to ensure fresh data
            self._clear_parameter_cache()

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
        # Check cache first if this endpoint is cacheable
        if endpoint_key in self._cache_ttl_config:
            cache_params = {"serialNum": serial_number}
            if extra_data:
                cache_params.update(extra_data)
            cache_key = self._get_cache_key(endpoint_key, **cache_params)

            if self._is_cache_valid(cache_key, endpoint_key):
                _LOGGER.debug("Cache hit for %s:%s", endpoint_key, serial_number)
                return self._response_cache[cache_key]["response"]

        # Make the actual request
        data = {"serialNum": serial_number}
        if extra_data:
            data.update(extra_data)

        response = await self._make_request("POST", self._ENDPOINTS[endpoint_key], data=data)

        # Cache the response if this endpoint is cacheable
        if endpoint_key in self._cache_ttl_config:
            self._cache_response(cache_key, response)
            _LOGGER.debug("Cached response for %s:%s", endpoint_key, serial_number)

        return response


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
        # Check if we have cached device discovery data
        cache_key = f"plant_{plant_id}"
        now = datetime.now()

        if (cache_key in self._device_cache and
            self._device_cache_expires and
            now < self._device_cache_expires):
            _LOGGER.debug("Using cached device discovery data for plant %s", plant_id)
            cached_data = self._device_cache[cache_key]
            serial_numbers = cached_data["serial_numbers"]
            gridboss_serials = cached_data["gridboss_serials"]
            device_info = cached_data["device_info"]
            parallel_groups = cached_data["parallel_groups"]
        else:
            _LOGGER.debug("Refreshing device discovery data for plant %s", plant_id)
            # Get fresh login data to access device information
            login_data = await self.login()

            serial_numbers = set()
            gridboss_serials = set()
            device_info = {}
            parallel_groups = []

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

            # Cache the device discovery data
            self._device_cache[cache_key] = {
                "serial_numbers": serial_numbers,
                "gridboss_serials": gridboss_serials,
                "device_info": device_info,
                "parallel_groups": parallel_groups
            }
            self._device_cache_expires = now + self._device_cache_ttl
            _LOGGER.debug("Cached device discovery data for %d devices", len(serial_numbers))

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
        # Only fetch if we have multiple devices (indicating a parallel group)
        parallel_energy_data = None
        if len(serial_numbers) > 1:
            try:
                # Use the first available serial number to get parallel group energy data
                first_serial = next(iter(serial_numbers))
                parallel_energy_data = await self.get_inverter_energy_info_parallel(
                    first_serial
                )
                _LOGGER.debug("Successfully retrieved parallel group energy data")
            except Exception as e:
                _LOGGER.warning("Failed to get parallel group energy data: %s", e)
        else:
            _LOGGER.debug("Single device setup, skipping parallel group energy data")

        # Organize results
        result = {
            "parallel_groups_info": parallel_groups,  # From login response
            "parallel_energy": parallel_energy_data,
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

    def _invalidate_cache_for_device(self, serial_number: str) -> None:
        """Invalidate cached responses for a specific device."""
        keys_to_remove = []
        for cache_key in self._response_cache:
            if (f"serialNum={serial_number}" in cache_key or
                f"inverterSn={serial_number}" in cache_key):
                keys_to_remove.append(cache_key)

        for key in keys_to_remove:
            del self._response_cache[key]

        if keys_to_remove:
            _LOGGER.debug(
                "Invalidated %d cached entries for device %s", len(keys_to_remove), serial_number
            )

    def _clear_parameter_cache(self) -> None:
        """Clear all parameter-related cache entries."""
        keys_to_remove = []
        for cache_key in self._response_cache:
            if (cache_key.startswith("parameter_read:") or
                cache_key.startswith("quick_charge_status:")):
                keys_to_remove.append(cache_key)

        for key in keys_to_remove:
            del self._response_cache[key]

        if keys_to_remove:
            _LOGGER.debug("Cleared %d parameter cache entries", len(keys_to_remove))

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

        # Determine endpoint to use
        if custom_endpoint:
            endpoint = custom_endpoint
        elif endpoint_key:
            endpoint = self._ENDPOINTS[endpoint_key]
        else:
            raise ValueError("Either endpoint_key or _custom_endpoint must be provided")

        # Check cache first if this endpoint is cacheable
        cache_key = None
        if endpoint_key and endpoint_key in self._cache_ttl_config:
            cache_params = {"inverterSn": inverter_sn, **kwargs}
            cache_key = self._get_cache_key(endpoint_key, **cache_params)

            if self._is_cache_valid(cache_key, endpoint_key):
                _LOGGER.debug("Cache hit for %s:%s", endpoint_key, inverter_sn)
                return self._response_cache[cache_key]["response"]

        data = {"inverterSn": inverter_sn, **kwargs}
        _LOGGER.debug("%s for inverter %s", operation.capitalize(), inverter_sn)

        try:
            response = await self._make_request("POST", endpoint, data)

            # Cache the response if this endpoint is cacheable
            if cache_key and endpoint_key in self._cache_ttl_config:
                self._cache_response(cache_key, response)
                _LOGGER.debug("Cached response for %s:%s", endpoint_key, inverter_sn)

            # Invalidate cache for write operations that might change device state
            if endpoint_key in ["parameter_write", "function_control"] or custom_endpoint:
                self._invalidate_cache_for_device(inverter_sn)
                _LOGGER.debug("Invalidated cache for device %s after %s", inverter_sn, operation)

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

    async def set_standby_mode(self, serial_number: str, enable: bool = True) -> Dict[str, Any]:
        """Set standby mode for specified inverter.

        Args:
            serial_number: The inverter serial number
            enable: True to enable standby mode, False to set to normal mode

        Returns:
            Dict containing the standby mode control response
        """
        # According to the curl examples:
        # Normal mode: enable=true (this sets the inverter to NORMAL operation)
        # Standby mode: enable=false (this sets the inverter to STANDBY)
        # The logic is reversed - when enable=True, we want normal mode (enable=true in API)
        # When enable=False, we want standby mode (enable=false in API)
        return await self.control_function_parameter(
            serial_number,
            "FUNC_SET_TO_STANDBY",
            not enable  # Reverse the logic based on curl examples
        )

    async def enable_normal_mode(self, serial_number: str) -> Dict[str, Any]:
        """Enable normal operation mode for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the normal mode enable response
        """
        return await self.set_standby_mode(serial_number, enable=True)

    async def enable_grid_peak_shaving(self, serial_number: str) -> Dict[str, Any]:
        """Enable grid peak shaving mode for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the peak shaving enable response
        """
        return await self.control_function_parameter(serial_number, "FUNC_GRID_PEAK_SHAVING", True)

    async def disable_grid_peak_shaving(self, serial_number: str) -> Dict[str, Any]:
        """Disable grid peak shaving mode for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the peak shaving disable response
        """
        return await self.control_function_parameter(serial_number, "FUNC_GRID_PEAK_SHAVING", False)

    async def enable_standby_mode(self, serial_number: str) -> Dict[str, Any]:
        """Enable standby mode for specified inverter.

        Args:
            serial_number: The inverter serial number

        Returns:
            Dict containing the standby mode enable response
        """
        return await self.set_standby_mode(serial_number, enable=False)

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring and debugging.

        Returns:
            Dict containing cache statistics
        """
        now = datetime.now()
        device_cache_valid = (
            self._device_cache_expires and now < self._device_cache_expires
        )

        # Count valid vs expired entries in response cache
        valid_entries = 0
        expired_entries = 0

        for cache_key in self._response_cache:
            endpoint_key = cache_key.split(":")[0]
            if self._is_cache_valid(cache_key, endpoint_key):
                valid_entries += 1
            else:
                expired_entries += 1

        return {
            "device_cache": {
                "entries": len(self._device_cache),
                "valid": device_cache_valid,
                "expires": (self._device_cache_expires.isoformat() 
                           if self._device_cache_expires else None)
            },
            "response_cache": {
                "total_entries": len(self._response_cache),
                "valid_entries": valid_entries,
                "expired_entries": expired_entries,
                "cache_hit_potential": (f"{valid_entries}/{len(self._response_cache)}" 
                                       if self._response_cache else "0/0")
            }
        }

    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._device_cache.clear()
        self._response_cache.clear()
        self._device_cache_expires = None
        _LOGGER.info("Cleared all cached data")
