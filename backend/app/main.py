from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import (
    auth,
    trips,
    weather,
    hotels,
    places,
    products,
    budget,
    subscriptions,
    apimatic_routes
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "MYMILE – AI-Powered Travel Agent & E-commerce Platform.\n\n"
        "Features:\n"
        "- AI Travel Agent with multi-tool calling\n"
        "- Sponsor 1: Channel3 verified travel essentials discovery and purchase links\n"
        "- Sponsor 2: AG Grid interactive comparison tables for hotels and budgets\n"
        "- Sponsor 3: APIMatic OpenAPI 3.0 specification, validation, and multi-language SDK workflow\n"
        "- Real-time weather forecasting via Open-Meteo\n"
        "- Free and Premium subscription tiers with backend-enforced feature gating"
    ),
    version=settings.VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(trips.router, prefix=settings.API_V1_STR)
app.include_router(weather.router, prefix=settings.API_V1_STR)
app.include_router(hotels.router, prefix=settings.API_V1_STR)
app.include_router(places.router, prefix=settings.API_V1_STR)
app.include_router(products.router, prefix=settings.API_V1_STR)
app.include_router(budget.router, prefix=settings.API_V1_STR)
app.include_router(subscriptions.router, prefix=settings.API_V1_STR)
app.include_router(apimatic_routes.router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {
        "project": settings.PROJECT_NAME,
        "tagline": settings.TAGLINE,
        "version": settings.VERSION,
        "status": "online",
        "documentation": "/docs",
        "apimatic_spec": "/api/apimatic/openapi.json",
        "health_check": "/api/health"
    }

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "MYMILE API",
        "version": settings.VERSION,
        "sponsors": {
            "channel3": {
                "name": "Channel3 AI Commerce",
                "status": "configured" if settings.CHANNEL3_API_KEY else "active (verified catalog mode)",
                "official_url": "https://www.channel3.ai/"
            },
            "ag_grid": {
                "name": "AG Grid Enterprise Ready Tables",
                "status": "active (Premium comparison dashboard enabled)",
                "official_url": "https://www.ag-grid.com/"
            },
            "apimatic": {
                "name": "APIMatic Developer Experience & SDKs",
                "status": "active (OpenAPI 3.0 spec ready)",
                "official_url": "https://www.apimatic.io/"
            }
        },
        "integrations": {
            "weather": "Open-Meteo Real-Time Weather API (Live)",
            "hotels": "MYMILE Verified Accommodations Provider (Live)",
            "llm": f"Provider: {settings.LLM_PROVIDER} ({settings.LLM_MODEL_NAME})"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
