from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.agents import llm
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.paypal_client import is_paypal_configured
from app.api.routes import (
    auth,
    trips,
    weather,
    hotels,
    places,
    products,
    budget,
    subscriptions,
    payments
)

# MYMILE's own INFO logs (e.g. Groq token usage) were dropped: Uvicorn configures only its
# own loggers. One handler on the "app" logger, with secret redaction.
configure_logging(settings.LOG_LEVEL)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "MYMILE – AI-Powered Travel Agent & E-commerce Platform.\n\n"
        "Features:\n"
        "- AI Travel Agent with multi-tool calling\n"
        "- Sponsor 1: Channel3 product search for trip essentials (purchase links for Premium)\n"
        "- Sponsor 2: AG Grid interactive comparison tables for hotels and budgets\n"
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
    allow_origins=settings.BACKEND_CORS_ORIGINS,  # explicit list, never "*"
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
app.include_router(payments.router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {
        "project": settings.PROJECT_NAME,
        "tagline": settings.TAGLINE,
        "version": settings.VERSION,
        "status": "online",
        "documentation": "/docs",
        "openapi_spec": "/openapi.json",
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
                "name": "Channel3 product search",
                "status": "configured" if (settings.CHANNEL3_API_KEY or "").strip() else "not configured",
                "official_url": "https://www.channel3.ai/"
            },
            "ag_grid": {
                "name": "AG Grid Enterprise Ready Tables",
                "status": "active (Premium comparison dashboard enabled)",
                "official_url": "https://www.ag-grid.com/"
            }
        },
        "integrations": {
            "weather": "Open-Meteo Real-Time Weather API (Live)",
            "hotels": "MYMILE Verified Accommodations Provider (Live)",
            # What this process will actually use (no key material).
            "llm": llm.describe()
        },
        # What THIS running process loaded (no ids, no secrets). If it says
        # false after editing backend/.env, the server was not restarted.
        "payments": {
            "paypal_configured": is_paypal_configured(),
            "paypal_environment": settings.PAYPAL_ENVIRONMENT.strip().lower(),
        },
    }

if __name__ == "__main__":
    import uvicorn
    # Also restart when backend/.env changes: settings are read once at startup.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True, reload_includes=[".env"])
