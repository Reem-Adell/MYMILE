from fastapi import APIRouter, Query
from app.schemas.weather_schema import WeatherResponse
from app.services.weather_service import get_weather_forecast

router = APIRouter(prefix="/weather", tags=["Weather"])

@router.get("", response_model=WeatherResponse)
async def get_weather(
    destination: str = Query(..., description="Destination city, region, or country"),
    days: int = Query(7, ge=1, le=14, description="Forecast days")
):
    """
    Returns real-time meteorological conditions and multi-day forecast for the destination.
    """
    return await get_weather_forecast(destination, days=days)
