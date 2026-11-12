from typing import List, Optional
from app.schemas.budget_schema import (
    BudgetBreakdown,
    BudgetCategoryDetail,
    BudgetOptimizationRequest,
    BudgetOptimizationResponse
)

def allocation_note(unallocated: float, currency: str = "USD") -> str:
    """What the allocation means, without implying actual spending."""
    if unallocated == 0:
        return ("Your whole budget is allocated across your stay and categories. These are planned "
                "limits, not a forecast of what you will spend.")
    if unallocated > 0:
        return f"{currency} {unallocated:,.2f} of your budget is not allocated to any category."
    return (f"Your stay plus the minimum category amounts exceed your budget by {currency} "
            f"{abs(unallocated):,.2f}.")


def optimize_budget(
    destination: str,
    duration_days: int,
    travelers: int,
    total_budget: Optional[float] = None,
    currency: str = "USD",
    selected_hotel_total: Optional[float] = None,
    stay_preference: str = "Boutique hotel",
    plan: str = "free"
) -> BudgetOptimizationResponse:
    """
    Budget optimization engine.
    For Free Plan: produces estimated baseline costs.
    For Premium Plan: performs multi-variable balancing of user budget against accommodation,
    dining experiences, local transit, activities, and travel gear essentials.
    """
    days = max(duration_days, 1)
    people = max(travelers, 1)
    is_premium = plan.lower() == "premium"
    
    # Baseline estimation when no budget provided or Free plan
    if not total_budget or total_budget <= 0:
        base_nightly = 180.0 if "luxury" in stay_preference.lower() else (140.0 if "boutique" in stay_preference.lower() else 75.0)
        hotel_cost = selected_hotel_total if selected_hotel_total else round(base_nightly * (days - 1 or 1), 2)
        food_cost = round(60.0 * days * people, 2)
        trans_cost = round(25.0 * days * people, 2)
        act_cost = round(40.0 * days * people, 2)
        essentials_cost = round(120.0 * people, 2)
        other_cost = round((food_cost + trans_cost) * 0.1, 2)
        total_est = round(hotel_cost + food_cost + trans_cost + act_cost + essentials_cost + other_cost, 2)
        
        breakdown = BudgetBreakdown(
            accommodation=hotel_cost,
            transportation=trans_cost,
            food=food_cost,
            activities=act_cost,
            travel_essentials=essentials_cost,
            contingency_and_other=other_cost,
            total_estimated=total_est,
            user_budget=total_budget,
            remaining_balance=None,
            currency=currency,
            status="estimated",
            allocation_mode="estimated",
            allocation_note="Estimated costs for this trip (no budget was set).",
        )
        return BudgetOptimizationResponse(
            plan_tier="free",
            total_budget=total_est,
            currency=currency,
            breakdown=breakdown,
            categories=[
                BudgetCategoryDetail(category="Accommodation", allocated_amount=hotel_cost, percentage_of_total=round((hotel_cost/total_est)*100, 1), description=f"Estimated {stay_preference} for {days} days"),
                BudgetCategoryDetail(category="Food & Dining", allocated_amount=food_cost, percentage_of_total=round((food_cost/total_est)*100, 1), description=f"Approx. $60/day per traveler across {days} days"),
                BudgetCategoryDetail(category="Transportation", allocated_amount=trans_cost, percentage_of_total=round((trans_cost/total_est)*100, 1), description="Local subway, trains, and transfers"),
                BudgetCategoryDetail(category="Sightseeing & Activities", allocated_amount=act_cost, percentage_of_total=round((act_cost/total_est)*100, 1), description="Attractions, temple/museum admissions, and guides"),
                BudgetCategoryDetail(category="Travel Essentials", allocated_amount=essentials_cost, percentage_of_total=round((essentials_cost/total_est)*100, 1), description="Channel3 recommended destination gear & packing needs"),
                BudgetCategoryDetail(category="Contingency & Other", allocated_amount=other_cost, percentage_of_total=round((other_cost/total_est)*100, 1), description="Emergency cushion and miscellaneous expenses")
            ],
            trade_off_analysis="Baseline estimate without budget constraint optimization. Upgrade to Premium to balance custom budgets.",
            savings_tips=["Book accommodations 4-6 weeks ahead for best boutique rates.", "Purchase multi-day transit passes."],
            comfort_score=78
        )
        
    # --- PREMIUM BUDGET OPTIMIZATION ALGORITHM ---
    budget = float(total_budget)
    
    # 1. Determine or anchor accommodation
    if selected_hotel_total:
        hotel_alloc = float(selected_hotel_total)
    else:
        # Default target: ~38% - 44% of total budget
        hotel_alloc = round(budget * 0.40, 2)
        
    unallocated = budget - hotel_alloc
    
    # If hotel exceeds 70% of budget, flag tight constraint
    if unallocated < (budget * 0.25):
        food_alloc = round(max(unallocated * 0.40, 30.0 * days * people), 2)
        trans_alloc = round(max(unallocated * 0.25, 15.0 * days * people), 2)
        act_alloc = round(max(unallocated * 0.20, 15.0 * days * people), 2)
        essentials_alloc = round(max(unallocated * 0.10, 30.0), 2)
        other_alloc = round(max(unallocated * 0.05, 10.0), 2)
    else:
        food_alloc = round(unallocated * 0.35, 2)
        trans_alloc = round(unallocated * 0.22, 2)
        act_alloc = round(unallocated * 0.24, 2)
        essentials_alloc = round(unallocated * 0.12, 2)
        other_alloc = round(unallocated * 0.07, 2)
        
    total_est = round(hotel_alloc + food_alloc + trans_alloc + act_alloc + essentials_alloc + other_alloc, 2)
    remaining = round(budget - total_est, 2)
    
    # Calculate comfort score (1 to 100)
    per_diem = (budget - hotel_alloc) / (days * people) if (days * people) > 0 else 50
    if per_diem >= 150:
        comfort_score = 96
    elif per_diem >= 100:
        comfort_score = 88
    elif per_diem >= 60:
        comfort_score = 79
    else:
        comfort_score = 64
        
    # Build trade-off analysis
    status = "balanced"
    if remaining >= 0:
        trade_off = (
            f"Your ${budget:,.2f} budget is well-balanced! Allocating ${hotel_alloc:,.2f} to stays leaves "
            f"${food_alloc:,.2f} for culinary discoveries and ${act_alloc:,.2f} for premier cultural experiences, "
            f"maintaining a healthy buffer of ${remaining:,.2f}."
        )
    else:
        status = "over_budget"
        deficit = abs(remaining)
        trade_off = (
            f"Estimated total exceeds budget by ${deficit:,.2f}. Consider selecting a slightly more affordable boutique stay "
            f"or opting for street dining and free cultural attractions to bring expenses back into balance."
        )
        
    categories = [
        BudgetCategoryDetail(category="Accommodation", allocated_amount=hotel_alloc, percentage_of_total=round((hotel_alloc/budget)*100, 1), description=f"Dedicated stay budget ({stay_preference})"),
        BudgetCategoryDetail(category="Food & Dining", allocated_amount=food_alloc, percentage_of_total=round((food_alloc/budget)*100, 1), description=f"Covers local specialties, artisan cafes, and dinner"),
        BudgetCategoryDetail(category="Transportation", allocated_amount=trans_alloc, percentage_of_total=round((trans_alloc/budget)*100, 1), description="Regional transit pass, airport shuttle, and metro"),
        BudgetCategoryDetail(category="Activities & Sightseeing", allocated_amount=act_alloc, percentage_of_total=round((act_alloc/budget)*100, 1), description="Curated tours, temple/museum entries, and experiences"),
        BudgetCategoryDetail(category="Travel Essentials", allocated_amount=essentials_alloc, percentage_of_total=round((essentials_alloc/budget)*100, 1), description="Channel3 verified gear (adapters, packing cubes, sling bag)"),
        BudgetCategoryDetail(category="Emergency Contingency", allocated_amount=other_alloc, percentage_of_total=round((other_alloc/budget)*100, 1), description="Flexible safety buffer for incidentals")
    ]
    
    savings_tips = [
        f"Save up to 15% on dining by exploring vibrant food markets like Nishiki Market or local bistros during lunch.",
        f"Get an unlimited subway / rail tourist card on day 1 to cap transportation expenses at ${trans_alloc:,.2f}.",
        f"Channel3 travel essentials can be bought before travel to avoid expensive airport markups."
    ]
    
    breakdown = BudgetBreakdown(
        accommodation=hotel_alloc,
        transportation=trans_alloc,
        food=food_alloc,
        activities=act_alloc,
        travel_essentials=essentials_alloc,
        contingency_and_other=other_alloc,
        total_estimated=total_est,
        user_budget=budget,
        remaining_balance=remaining,
        currency=currency,
        status=status,
        allocation_mode="allocated",
        allocated_total=total_est,
        unallocated_budget=remaining,
        fully_allocated=remaining == 0,
        allocation_note=allocation_note(remaining, currency),
    )
    
    return BudgetOptimizationResponse(
        plan_tier="premium",
        total_budget=budget,
        currency=currency,
        breakdown=breakdown,
        categories=categories,
        trade_off_analysis=trade_off,
        savings_tips=savings_tips,
        comfort_score=comfort_score
    )
