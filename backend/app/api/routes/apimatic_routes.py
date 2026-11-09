from fastapi import APIRouter, Request, HTTPException
from fastapi.openapi.utils import get_openapi
from typing import Dict, Any
from app.services.apimatic_service import get_apimatic_metadata, validate_spec_with_apimatic

router = APIRouter(prefix="/apimatic", tags=["APIMatic Sponsor Integration"])

@router.get("/portal-info")
async def apimatic_portal_info() -> Dict[str, Any]:
    """
    Sponsor Integration: APIMatic (https://www.apimatic.io/).
    Provides API Transformation metadata, CodeGen SDK capabilities,
    and developer portal configuration.
    """
    return get_apimatic_metadata()

@router.get("/openapi.json")
async def get_apimatic_openapi_spec(request: Request) -> Dict[str, Any]:
    """
    Returns the OpenAPI 3.0.3 specification specifically optimized for APIMatic's
    CodeGen engine and interactive developer documentation portal.
    """
    app = request.app
    openapi_schema = get_openapi(
        title="MYMILE Public Travel API",
        version="1.0.0",
        description="APIMatic-ready OpenAPI 3.0 specification for MYMILE AI Travel Agent and E-commerce Platform.",
        routes=app.routes,
    )
    # Add APIMatic custom extensions
    openapi_schema["info"]["x-apimatic-portal"] = {
        "theme": "mymile-purple-yellow",
        "generate_sdks": ["typescript", "python", "java", "csharp"],
        "docs_url": "https://apimatic.io"
    }
    return openapi_schema

@router.post("/validate")
async def validate_apimatic_spec(request: Request) -> Dict[str, Any]:
    """
    Validates MYMILE's OpenAPI spec against APIMatic standards.
    """
    app = request.app
    spec = get_openapi(
        title="MYMILE Public Travel API",
        version="1.0.0",
        routes=app.routes
    )
    return await validate_spec_with_apimatic(spec)

@router.get("/sdk/{language}")
async def get_generated_sdk_snippet(language: str) -> Dict[str, Any]:
    """
    Demonstrates APIMatic's CodeGen capability by providing client initialization snippets
    in TypeScript and Python generated for the MYMILE API.
    """
    lang = language.lower()
    if lang in ["ts", "typescript"]:
        code = (
            "import { MyMileClient } from '@mymile/travel-sdk';\n\n"
            "const client = new MyMileClient({ apiKey: 'YOUR_API_KEY' });\n\n"
            "// Plan a personalized trip with AI Agent\n"
            "const plan = await client.trips.plan({\n"
            "  destination: 'Kyoto, Japan',\n"
            "  departureDate: '2026-04-08',\n"
            "  returnDate: '2026-04-15',\n"
            "  purpose: 'Tourism',\n"
            "  plan: 'premium',\n"
            "  totalBudget: 4500\n"
            "});\n"
            "console.log('Match score:', plan.matchScore);\n"
            "console.log('Recommended stay:', plan.recommendedHotel.name);"
        )
        return {"language": "TypeScript", "package": "@mymile/travel-sdk", "code": code}
    elif lang in ["py", "python"]:
        code = (
            "from mymile_travel_sdk import MyMileClient\n\n"
            "client = MyMileClient(api_key='YOUR_API_KEY')\n\n"
            "# Plan trip with MYMILE AI Agent\n"
            "trip = client.trips.plan(\n"
            "    destination='Kyoto, Japan',\n"
            "    departure_date='2026-04-08',\n"
            "    return_date='2026-04-15',\n"
            "    purpose='Tourism',\n"
            "    plan='premium',\n"
            "    total_budget=4500.0\n"
            ")\n"
            "print(f'Recommended Hotel: {trip.recommended_hotel.name}')\n"
            "print(f'Budget Balance: ${trip.budget_breakdown.remaining_balance}')"
        )
        return {"language": "Python", "package": "mymile-travel-sdk", "code": code}
    else:
        raise HTTPException(status_code=400, detail="Supported languages: 'typescript', 'python'")
