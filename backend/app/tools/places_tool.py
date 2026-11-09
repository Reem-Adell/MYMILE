from typing import Dict, Any
from app.services.places_service import search_places

def run_places_tool(destination: str) -> Dict[str, Any]:
    """Retrieves top cultural, historical, and sightseeing attractions for a destination."""
    res = search_places(destination)
    return res.model_dump()
