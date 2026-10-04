import logging
from contextlib import asynccontextmanager
from typing import Any
import httpx
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

# 1. Setup Production Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mcp-weather-server")

# 2. Initialize the Modern v2 MCPServer instance
mcp_server = MCPServer("weather")

# ... (Keep your weather models and tool functions exactly as they are) ...

# --- THE ABSOLUTE SOLUTION ---
# Disable DNS rebinding protection so the server accepts HTTP requests crossing the Docker bridge
security_settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)



NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"


# --- Models ---
class Alert(BaseModel):
    event: str = Field(description="The kind of weather event")
    area: str = Field(description="The area the alert covers")
    severity: str = Field(description="How severe the event is")
    description: str = Field(description="What is happening")
    instructions: str = Field(description="What people in the area should do")


class Period(BaseModel):
    name: str = Field(description="Label for the period, e.g. Tonight or Tuesday")
    temperature: int = Field(description="Forecast temperature")
    temperature_unit: str = Field(description="Unit of the temperature, F or C")
    wind_speed: str = Field(description="Wind speed, e.g. 10 to 15 mph")
    wind_direction: str = Field(description="Wind direction as a compass point")
    detailed_forecast: str = Field(description="Prose description of the period")


class Forecast(BaseModel):
    latitude: float = Field(description="Latitude the forecast is for")
    longitude: float = Field(description="Longitude the forecast is for")
    periods: list[Period] = Field(description="The forecast periods, soonest first")


# --- Async NWS Client ---
async def make_nws_request(url: str) -> dict[str, Any] | None:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"NWS API request failed on {url}: {str(e)}")
            return None


# --- Tools ---
@mcp_server.tool()
async def get_alerts(state: str) -> list[Alert]:
    """Get weather alerts for a US state."""
    logger.info(f"Fetching active weather alerts for state: {state}")
    url = f"{NWS_API_BASE}/alerts/active/area/{state.upper()}"
    data = await make_nws_request(url)
    if not data or "features" not in data:
        raise ValueError(f"Unable to fetch alerts for {state.upper()}.")
    return [
        Alert(
            event=props.get("event") or "Unknown",
            area=props.get("areaDesc") or "Unknown",
            severity=props.get("severity") or "Unknown",
            description=props.get("description") or "No description available",
            instructions=props.get("instruction") or "No specific instructions provided",
        )
        for props in (feature["properties"] for feature in data["features"])
    ]


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

    if not points_data or "properties" not in points_data:
        raise ValueError("Unable to fetch forecast data for this location.")

    forecast_url = points_data["properties"].get("forecast")
    if not forecast_url:
        raise ValueError("Forecast URL missing from location grid metadata.")

    forecast_data = await make_nws_request(forecast_url)
    if not forecast_data or "properties" not in forecast_data:
        raise ValueError("Unable to fetch detailed forecast.")

    periods = forecast_data["properties"].get("periods", [])[:5]
    if not periods:
        raise ValueError("No forecast periods available.")

    return Forecast(
        latitude=latitude,
        longitude=longitude,
        periods=[
            Period(
                name=str(period.get("name") or "Unknown"),
                temperature=int(period.get("temperature") or 0),
                # Safely fallback if field nomenclature changes slightly
                temperature_unit=str(period.get("temperatureUnit") or period.get("temperature_unit") or "F"),
                wind_speed=str(period.get("windSpeed") or period.get("wind_speed") or "Unknown"),
                wind_direction=str(period.get("windDirection") or period.get("wind_direction") or "Unknown"),
                detailed_forecast=str(
                    period.get("detailedForecast") or period.get("detailed_forecast") or "No description available."),
            )
            for period in periods
        ],
    )


# 3. Create the streamable sub-application engine
#mcp_app = mcp_server.streamable_http_app()
mcp_app = mcp_server.streamable_http_app(streamable_http_path="/")
# 3. Create the streamable sub-application engine
# FIX: Explicitly enforce binding to 0.0.0.0 to unlock outside Docker container access
#mcp_app = mcp_server.streamable_http_app(host="0.0.0.0")



# 4. CRITICAL: Bind the MCP background engine lifespans directly to the parent FastAPI app
@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    # This securely hooks up the internal background processes when Uvicorn boots
    async with mcp_app.router.lifespan_context(fastapi_app):
        yield


# 5. Initialize Parent Application with the combined lifespan
app = FastAPI(title="Production v2 MCP Weather Engine", lifespan=lifespan)

# Mount the routes securely
app.mount("/mcp", mcp_app)


# Add a simple health check route so you can test if the server is responsive in a browser
@app.get("/")
async def health_check():
    return {"status": "MCP Server wrapper is live and healthy"}


if __name__ == "__main__":
    import uvicorn

    # Bind to all interfaces inside the Docker container on port 8000
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
