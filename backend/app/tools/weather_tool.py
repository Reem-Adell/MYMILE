import asyncio
from typing import Dict, Any
from app.services.weather_service import get_weather_forecast

async def run_weather_tool(destination: str, days: int = 7) -> Dict[str, Any]:
    """Retrieves live meteorological conditions and forecast for a destination."""
    res = await get_weather_forecast(destination, days)
    return res.model_dump()

# Synchronous wrapper for standard tool calling
def weather_tool_sync(destination: str, days: int = 7) -> Dict[str, Any]:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            # or direct thread runner
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                return executor.submit(asyncio.run, get_weather_forecast(destination, days)).result()
        else:
            return asyncio.run(get_weather_forecast(destination, days)).model_dump()
    except Exception:
        return asyncio.run(get_weather_forecast(destination, days)).model_dump()
