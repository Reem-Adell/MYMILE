from fastapi import APIRouter, Depends, HTTPException
from app.api.routes.auth import get_effective_plan
from app.schemas.trip_schema import TripPlanRequest, TripPlanResponse, TripChatRequest, TripChatResponse
from app.agents.travel_agent import plan_trip_agent, chat_with_trip_agent

router = APIRouter(prefix="/trips", tags=["Trips & AI Agent"])

# `plan` below is server-verified from the Bearer token (guests -> 'free') and is
# handed to the agent as a separate argument. Any `plan` field a client puts in
# the request body is not part of the schema and is ignored.

@router.post("/plan", response_model=TripPlanResponse)
async def create_trip_plan(req: TripPlanRequest, plan: str = Depends(get_effective_plan)):
    """
    Core AI Travel Agent endpoint.
    Retrieves weather, finds verified stays, generates itinerary, estimates/optimizes expenses,
    and returns Channel3 travel essentials.
    """
    try:
        result = await plan_trip_agent(req, plan=plan)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Agent travel planning failed: {str(e)}")

@router.post("/chat", response_model=TripChatResponse)
async def chat_with_companion(req: TripChatRequest, plan: str = Depends(get_effective_plan)):
    """
    Conversational AI Assistant endpoint for follow-up questions and real-time trip modifications.
    """
    try:
        res = await chat_with_trip_agent(req, plan=plan)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Companion chat failed: {str(e)}")
