"""Tests for EG4 Inverter API Client."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

# Add the parent directory to the path so we can import the API
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from eg4_inverter_api import EG4InverterAPI
from eg4_inverter_api.exceptions import EG4APIError, EG4AuthError, EG4ConnectionError

# Try to import secrets
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from secrets import EG4_USERNAME, EG4_PASSWORD
except ImportError:
    print("Warning: secrets.py not found. Please create it with EG4_USERNAME and EG4_PASSWORD")
    EG4_USERNAME = None
    EG4_PASSWORD = None


class TestEG4InverterAPI:
    """Test suite for EG4 Inverter API."""

    def __init__(self):
        """Initialize test suite."""
        self.samples_dir = Path(__file__).parent.parent / "samples"
        self.samples_dir.mkdir(exist_ok=True)
        
        if not EG4_USERNAME or not EG4_PASSWORD:
            print("Skipping live API tests - no credentials provided")
            return

        self.api = EG4InverterAPI(
            username=EG4_USERNAME,
            password=EG4_PASSWORD
        )

    async def save_sample(self, name: str, data: Any):
        """Save API response as sample."""
        sample_file = self.samples_dir / f"{name}.json"
        with open(sample_file, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"Saved sample: {sample_file}")

    async def test_authentication(self):
        """Test API authentication."""
        print("\n=== Testing Authentication ===")
        
        try:
            result = await self.api.login()
            await self.save_sample("login", result)
            print("✅ Login successful")
            
            # Test session persistence
            await self.api._ensure_authenticated()
            print("✅ Session persistence working")
            
        except EG4AuthError as e:
            print(f"❌ Authentication failed: {e}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error during authentication: {e}")
            return False
        
        return True

    async def test_plants_discovery(self):
        """Test plant/station discovery."""
        print("\n=== Testing Plants Discovery ===")
        
        try:
            plants = await self.api.get_plants()
            await self.save_sample("plants", plants)
            
            print(f"✅ Found {len(plants)} plants:")
            for plant in plants:
                print(f"  - {plant.get('name')} (ID: {plant.get('plantId')})")
            
            return plants
            
        except Exception as e:
            print(f"❌ Plants discovery failed: {e}")
            return None

    async def test_device_discovery(self, plant_id: str):
        """Test device discovery for a plant."""
        print(f"\n=== Testing Device Discovery for Plant {plant_id} ===")
        
        # Extract devices from login response (already available)
        devices = []
        try:
            # Read the login response to get device info
            login_file = self.samples_dir / "login.json"
            if login_file.exists():
                with open(login_file, "r") as f:
                    login_data = json.load(f)
                
                # Extract devices from plants array
                for plant in login_data.get("plants", []):
                    if str(plant.get("plantId")) == str(plant_id):
                        for device in plant.get("inverters", []):
                            serial = device.get("serialNum")
                            model = device.get("deviceTypeText4APP", "Unknown")
                            if serial:
                                devices.append({
                                    "serial": serial, 
                                    "model": model, 
                                    "source": "login_response",
                                    "deviceType": device.get("deviceType"),
                                    "subDeviceType": device.get("subDeviceType"),
                                    "lost": device.get("lost", False)
                                })
                
                print(f"✅ Found {len(devices)} devices from login response:")
                for device in devices:
                    status = "LOST" if device.get("lost") else "ONLINE"
                    print(f"  - {device['model']} ({device['serial']}) - {status}")
            
            # Try the API endpoints too (they might work with different parameters)
            try:
                parallel_groups = await self.api.get_parallel_group_details(plant_id)
                await self.save_sample(f"parallel_groups_{plant_id}", parallel_groups)
                print("✅ Parallel groups retrieved")
            except Exception as e:
                print(f"⚠️ Parallel groups failed: {e}")
            
            try:
                inverter_overview = await self.api.get_inverter_overview(plant_id)
                await self.save_sample(f"inverter_overview_{plant_id}", inverter_overview)
                print("✅ Inverter overview retrieved")
            except Exception as e:
                print(f"⚠️ Inverter overview failed: {e}")
            
            return devices
            
        except Exception as e:
            print(f"❌ Device discovery failed: {e}")
            return []

    async def test_device_data(self, devices: list):
        """Test data retrieval for discovered devices."""
        print(f"\n=== Testing Device Data Retrieval ===")
        
        for device in devices[:3]:  # Limit to first 3 devices to avoid rate limiting
            serial = device["serial"]
            model = device["model"]
            
            print(f"\n--- Testing device {model} ({serial}) ---")
            
            # Check if this is a GridBOSS device
            is_gridboss = "gridboss" in model.lower() or "grid boss" in model.lower()
            
            if is_gridboss:
                await self.test_gridboss_data(serial)
            else:
                await self.test_inverter_data(serial)

    async def test_inverter_data(self, serial: str):
        """Test data retrieval for standard inverter."""
        print(f"  Testing standard inverter data for {serial}")
        
        try:
            # Test runtime data
            runtime = await self.api.get_inverter_runtime(serial)
            await self.save_sample(f"runtime_{serial}", runtime)
            print("    ✅ Runtime data retrieved")
            
            # Test energy data
            energy = await self.api.get_inverter_energy_info(serial)
            await self.save_sample(f"energy_{serial}", energy)
            print("    ✅ Energy data retrieved")
            
            # Test battery data
            battery = await self.api.get_battery_info(serial)
            await self.save_sample(f"battery_{serial}", battery)
            print("    ✅ Battery data retrieved")
            
            # Check for individual batteries
            if isinstance(battery, dict) and "batteryArray" in battery:
                battery_count = len(battery["batteryArray"])
                print(f"    ✅ Found {battery_count} individual batteries")
            
            # Test parallel energy info (may not be applicable to all devices)
            try:
                parallel_energy = await self.api.get_inverter_energy_info_parallel(serial)
                await self.save_sample(f"parallel_energy_{serial}", parallel_energy)
                print("    ✅ Parallel energy data retrieved")
            except Exception as e:
                print(f"    ⚠️ Parallel energy data not available: {e}")
                
        except Exception as e:
            print(f"    ❌ Inverter data retrieval failed: {e}")

    async def test_gridboss_data(self, serial: str):
        """Test data retrieval for GridBOSS device."""
        print(f"  Testing GridBOSS data for {serial}")
        
        try:
            midbox_data = await self.api.get_midbox_runtime(serial)
            await self.save_sample(f"midbox_{serial}", midbox_data)
            print("    ✅ MidBox runtime data retrieved")
            
        except Exception as e:
            print(f"    ❌ GridBOSS data retrieval failed: {e}")

    async def test_comprehensive_data(self, plant_id: str):
        """Test comprehensive data retrieval."""
        print(f"\n=== Testing Comprehensive Data Retrieval for Plant {plant_id} ===")
        
        try:
            all_data = await self.api.get_all_device_data(plant_id)
            await self.save_sample(f"comprehensive_{plant_id}", all_data)
            
            device_count = len(all_data.get("devices", {}))
            print(f"✅ Comprehensive data retrieved for {device_count} devices")
            
            # Report on errors
            error_count = 0
            for serial, data in all_data.get("devices", {}).items():
                if "error" in data:
                    error_count += 1
                    print(f"  ⚠️ Error for device {serial}: {data['error']}")
            
            if error_count == 0:
                print("✅ All devices retrieved successfully")
            else:
                print(f"⚠️ {error_count} devices had errors")
                
        except Exception as e:
            print(f"❌ Comprehensive data retrieval failed: {e}")

    async def run_all_tests(self):
        """Run all tests."""
        print("🚀 Starting EG4 Inverter API Tests")
        
        if not EG4_USERNAME or not EG4_PASSWORD:
            print("❌ No credentials provided - skipping tests")
            return
        
        try:
            # Test authentication
            if not await self.test_authentication():
                print("❌ Authentication failed - stopping tests")
                return
            
            # Test plants discovery
            plants = await self.test_plants_discovery()
            if not plants:
                print("❌ No plants found - stopping tests")
                return
            
            # Test each plant
            for plant in plants[:1]:  # Test first plant only
                plant_id = plant.get("plantId")
                plant_name = plant.get("name", "Unknown")
                
                print(f"\n🏭 Testing plant: {plant_name} ({plant_id})")
                
                # Test device discovery
                devices = await self.test_device_discovery(plant_id)
                if not devices:
                    print(f"⚠️ No devices found in plant {plant_name}")
                    continue
                
                # Test device data
                await self.test_device_data(devices)
                
                # Test comprehensive data
                await self.test_comprehensive_data(plant_id)
        
        finally:
            await self.api.close()
        
        print("\n✅ All tests completed!")


async def main():
    """Run the test suite."""
    test_suite = TestEG4InverterAPI()
    await test_suite.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())