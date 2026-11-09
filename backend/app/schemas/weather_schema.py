from typing import List, Optional
from pydantic import BaseModel

class WeatherForecastDay(BaseModel):
    date: str
    condition: str
    temp_min_c: float
    temp_max_c: float
    temp_min_f: float
    temp_max_f: float
    precipitation_prob: Optional[int] = 0
    icon: Optional[str] = "sun"
    summary: Optional[str] = None

class WeatherResponse(BaseModel):
    destination: str
    latitude: float
    longitude: float
    current_temp_c: float
    current_condition: str
    packing_tip: str
    forecast: List[WeatherForecastDay]
    source: str = "Open-Meteo Real-Time Weather API"
