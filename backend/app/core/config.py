import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    PROJECT_NAME: str = "MYMILE - AI Travel Agent & E-commerce Platform"
    TAGLINE: str = "Your Smile, With You Every Mile."
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    
    # Security
    SECRET_KEY: str = Field(default="mymile-hackathon-super-secret-key-change-in-production-2026", env="SECRET_KEY")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "*"
    ]
    
    # AI / LLM Configuration
    # Supported providers: "gemini", "openai"
    LLM_PROVIDER: str = Field(default="gemini", env="LLM_PROVIDER")
    GEMINI_API_KEY: Optional[str] = Field(default=None, env="GEMINI_API_KEY")
    OPENAI_API_KEY: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    LLM_MODEL_NAME: str = Field(default="gemini-1.5-flash", env="LLM_MODEL_NAME")
    
    # Sponsor: Channel3 E-commerce Integration
    # Official docs: https://www.channel3.ai/
    CHANNEL3_API_KEY: Optional[str] = Field(default=None, env="CHANNEL3_API_KEY")
    CHANNEL3_BASE_URL: str = Field(default="https://api.channel3.ai/v1", env="CHANNEL3_BASE_URL")
    
    # Weather API (Default: Open-Meteo, 100% free and real without API key, or OpenWeatherMap)
    WEATHER_API_KEY: Optional[str] = Field(default=None, env="WEATHER_API_KEY")
    WEATHER_BASE_URL: str = Field(default="https://api.open-meteo.com/v1", env="WEATHER_BASE_URL")
    
    # Hotels & Places API
    HOTEL_API_KEY: Optional[str] = Field(default=None, env="HOTEL_API_KEY")
    HOTEL_BASE_URL: Optional[str] = Field(default=None, env="HOTEL_BASE_URL")
    PLACES_API_KEY: Optional[str] = Field(default=None, env="PLACES_API_KEY")
    PLACES_BASE_URL: Optional[str] = Field(default=None, env="PLACES_BASE_URL")
    
    # Sponsor: APIMatic Integration
    # Official docs: https://www.apimatic.io/
    APIMATIC_API_KEY: Optional[str] = Field(default=None, env="APIMATIC_API_KEY")
    APIMATIC_BASE_URL: str = Field(default="https://api.apimatic.io/v1", env="APIMATIC_BASE_URL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
