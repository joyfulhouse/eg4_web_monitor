"""Test plant/station configuration API endpoints."""

import asyncio
import json
import logging
from custom_components.eg4_web_monitor.eg4_inverter_api.client import EG4InverterAPI
from secrets import EG4_USERNAME, EG4_PASSWORD, EG4_BASE_URL

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)


async def main():
    """Test plant configuration endpoints."""
    async with EG4InverterAPI(
        username=EG4_USERNAME,
        password=EG4_PASSWORD,
        base_url=EG4_BASE_URL,
    ) as api:
        # Get list of plants to find plant ID
        plants = await api.get_plants()
        print(f"\n=== Found {len(plants)} plants ===")
        for plant in plants:
            print(f"Plant ID: {plant.get('plantId')}, Name: {plant.get('name')}")

        if not plants:
            print("No plants found!")
            return

        # Save plants list
        with open("samples/plant_list.json", "w") as f:
            json.dump(plants, f, indent=2)
        print("\nSaved: samples/plant_list.json")

        # Use the first plant for testing
        plant_id = plants[0].get("plantId")
        print(f"\n=== Testing with Plant ID: {plant_id} ===")

        # Test 1: Get plant details from viewer endpoint
        # This endpoint returns detailed plant information
        session = await api._get_session()
        url = f"{api.base_url}/WManage/web/config/plant/list/viewer"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json",
            "Cookie": f"JSESSIONID={api._session_id}",
        }
        data_str = f"page=1&rows=20&searchText=&targetPlantId={plant_id}&sort=createDate&order=desc"

        async with session.post(url, headers=headers, data=data_str) as response:
            plant_details = await response.json()
            print("\n=== Plant Details Response ===")
            print(json.dumps(plant_details, indent=2))

            with open("samples/plant_details.json", "w") as f:
                json.dump(plant_details, f, indent=2)
            print("\nSaved: samples/plant_details.json")

        # Test 2: Get plant edit page data (read current configuration)
        # This shows us what fields are available for configuration
        url = f"{api.base_url}/WManage/web/config/plant/edit/{plant_id}"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Cookie": f"JSESSIONID={api._session_id}",
        }

        async with session.get(url, headers=headers) as response:
            html_content = await response.text()
            print("\n=== Plant Edit Page (first 1000 chars) ===")
            print(html_content[:1000])

            with open("samples/plant_edit_page.html", "w") as f:
                f.write(html_content)
            print("\nSaved: samples/plant_edit_page.html")

        # Test 3: Parse the plant details to extract editable fields
        if plant_details.get("rows"):
            plant_data = plant_details["rows"][0]
            print("\n=== Editable Plant Fields ===")
            print(f"Plant ID: {plant_data.get('plantId')}")
            print(f"Name: {plant_data.get('name')}")
            print(f"Nominal Power: {plant_data.get('nominalPower')} W")
            print(f"Continent: {plant_data.get('continent')}")
            print(f"Region: {plant_data.get('region')}")
            print(f"Country: {plant_data.get('country')}")
            print(f"Timezone: {plant_data.get('timezone')}")
            print(f"Daylight Saving Time: {plant_data.get('daylightSavingTime')}")
            print(f"Longitude: {plant_data.get('longitude')}")
            print(f"Latitude: {plant_data.get('latitude')}")
            print(f"Create Date: {plant_data.get('createDate')}")

            # Create a summary of editable fields
            editable_fields = {
                "plantId": plant_data.get("plantId"),
                "name": plant_data.get("name"),
                "nominalPower": plant_data.get("nominalPower"),
                "continent": plant_data.get("continent"),
                "region": plant_data.get("region"),
                "country": plant_data.get("country"),
                "timezone": plant_data.get("timezone"),
                "daylightSavingTime": plant_data.get("daylightSavingTime"),
                "longitude": plant_data.get("longitude"),
                "latitude": plant_data.get("latitude"),
                "createDate": plant_data.get("createDate"),
            }

            with open("samples/plant_editable_fields.json", "w") as f:
                json.dump(editable_fields, f, indent=2)
            print("\nSaved: samples/plant_editable_fields.json")


if __name__ == "__main__":
    asyncio.run(main())
