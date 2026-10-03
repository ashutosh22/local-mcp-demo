import logging
from typing import Any
import httpx
from fastapi import FastAPI
from mcp.server import MCPServer
from pydantic import BaseModel, Field, RootModel


# 1. Setup Production Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("mcp-weather-server")

# 2. Initialize the Modern v2 MCPServer instance
# MCPServer handles tool registration and core protocol bindings natively.
mcp_server = MCPServer("weather")

# Constants
NWS_API_BASE = "https://weather.gov"
USER_AGENT = "weather-app/1.0"


# 3. Define Output Pydantic Schemas Natively
class Alert(BaseModel):
    """One active weather alert."""
    event: str = Field(description="The kind of weather event")
    area: str = Field(description="The area the alert covers")
    severity: str = Field(description="How severe the event is")
    description: str = Field(description="What is happening")
    instructions: str = Field(description="What people in the area should do")

class Alerts(RootModel[list[Alert]]):
    """The output schema of get_alerts: a top-level array, not an object."""

class Period(BaseModel):
    """One period of a forecast."""
    name: str = Field(description="Label for the period, e.g. Tonight or Tuesday")
    temperature: int = Field(description="Forecast temperature")
    temperature_unit: str = Field(description="Unit of the temperature, F or C")
    wind_speed: str = Field(description="Wind speed, e.g. 10 to 15 mph")
    wind_direction: str = Field(description="Wind direction as a compass point")
    detailed_forecast: str = Field(description="Prose description of the period")

class Forecast(BaseModel):
    """The output schema of get_forecast: the object case, for contrast."""
    latitude: float = Field(description="Latitude the forecast is for")
    longitude: float = Field(description="Longitude the forecast is for")
    periods: list[Period] = Field(description="The forecast periods, soonest first")


# 4. Async API Request Engine
async def make_nws_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling using standard httpx."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"NWS API request failed on {url}: {str(e)}")
            return None

# 5. Register Tools Natively Using @mcp_server.tool()
@mcp_server.tool()
async def get_alerts(state: str) -> Alerts:
    """Get weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, NY)
    """
    logger.info(f"Fetching active weather alerts for state: {state}")
    url = f"{NWS_API_BASE}/alerts/active/area/{state.upper()}"
    data = await make_nws_request(url)

    if not data or "features" not in data:
        raise ValueError(f"Unable to fetch alerts for {state.upper()}.")

        # Pass the list directly into model_validate
    return Alerts.model_validate(
        [
            Alert(
                event=props.get("event") or "Unknown",
                area=props.get("areaDesc") or "Unknown",
                severity=props.get("severity") or "Unknown",
                description=props.get("description") or "No description available",
                instructions=props.get("instruction") or "No specific instructions provided",
            )
            for props in (feature["properties"] for feature in data["features"])
        ]
    )

@mcp_server.tool()
async def get_forecast(latitude: float, longitude: float) -> Forecast:
    """Get weather forecast for a location coordinate.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    logger.info(f"Fetching forecast grid points: lat={latitude}, lon={longitude}")
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await make_nws_request(points_url)

    if not points_data:
        raise ValueError("Unable to fetch forecast data for this location.")

    forecast_url = points_data["properties"]["forecast"]
    forecast_data = await make_nws_request(forecast_url)

    if not forecast_data:
        raise ValueError("Unable to fetch detailed forecast.")

    periods = forecast_data["properties"]["periods"][:5]
    if not periods:
        raise ValueError("No forecast periods available.")

    return Forecast(
        latitude=latitude,
        longitude=longitude,
        periods=[
            Period(
                name=period["name"],
                temperature=period["temperature"],
                temperature_unit=period["temperatureUnit"],
                wind_speed=period["windSpeed"],
                wind_direction=period["windDirection"],
                detailed_forecast=period["detailedForecast"],
            )
            for period in periods
        ],
    )

# 6. Initialize Parent FastAPI Application and Mount v2 App
app = FastAPI(title="Production v2 MCP Weather Engine")

# Generate the streamable ASGI application endpoint automatically from the server engine
mcp_app = mcp_server.streamable_http_app()

# Mount it cleanly onto the /mcp routing base endpoint
app.mount("/mcp", mcp_app)

if __name__ == "__main__":
    import uvicorn
    logger.info("Launching Production v2 Weather MCP Application over HTTP Stream...")
    uvicorn.run(app, host="0.0.0.0", port=8000)