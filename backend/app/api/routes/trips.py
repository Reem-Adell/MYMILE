from fastapi import APIRouter, HTTPException
from app.schemas.trip_schema import TripPlanRequest, TripPlanResponse, TripChatRequest, TripChatResponse
from app.agents.travel_agent import plan_trip_agent, chat_with_trip_agent

router = APIRouter(prefix="/trips", tags=["Trips & AI Agent"])

@router.post("/plan", response_model=TripPlanResponse)
async def create_trip_plan(req: TripPlanRequest):
    """
    Core AI Travel Agent endpoint.
    Retrieves weather, finds verified stays, generates itinerary, estimates/optimizes expenses,
    and returns Channel3 travel essentials.
    """
    try:
        plan = await plan_trip_agent(req)
        return plan
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Agent travel planning failed: {str(e)}")

@router.post("/chat", response_model=TripChatResponse)
async def chat_with_companion(req: TripChatRequest):
    """
    Conversational AI Assistant endpoint for follow-up questions and real-time trip modifications.
    """
    try:
        res = await chat_with_trip_agent(req)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Companion chat failed: {str(e)}")
