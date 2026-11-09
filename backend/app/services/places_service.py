from typing import List
from app.schemas.places_schema import PlaceItem, PlacesSearchResponse

REAL_PLACES_DB = [
    # Kyoto
    {
        "id": "plc-kyo-01",
        "destination": "kyoto",
        "name": "Fushimi Inari Shrine",
        "category": "Culture & Heritage",
        "description": "Famous Shinto shrine dedicated to the god of rice, renowned for thousands of vibrant vermilion torii gates winding up the sacred mountain.",
        "rating": 4.9,
        "estimated_duration_hours": 2.5,
        "estimated_ticket_price": 0.0,
        "image_url": "https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?auto=format&fit=crop&w=800&q=80",
        "best_time_to_visit": "Early morning (7:00 AM) to avoid crowds"
    },
    {
        "id": "plc-kyo-02",
        "destination": "kyoto",
        "name": "Kinkaku-ji (The Golden Pavilion)",
        "category": "Historical Landmark",
        "description": "Zen Buddhist temple whose top two floors are completely covered in gleaming gold leaf, overlooking the serene Kyoko-chi mirror pond.",
        "rating": 4.8,
        "estimated_duration_hours": 1.5,
        "estimated_ticket_price": 5.0,
        "image_url": "https://images.unsplash.com/photo-1503899036084-c55cdd92da26?auto=format&fit=crop&w=800&q=80",
        "best_time_to_visit": "Late morning for optimal sun reflection"
    },
    {
        "id": "plc-kyo-03",
        "destination": "kyoto",
        "name": "Arashiyama Bamboo Grove & Tenryu-ji",
        "category": "Nature & Zen",
        "description": "Towering bamboo stalks that sway in the gentle breeze, creating an otherworldly auditory experience alongside UNESCO World Heritage Zen gardens.",
        "rating": 4.8,
        "estimated_duration_hours": 3.0,
        "estimated_ticket_price": 4.0,
        "image_url": "https://images.unsplash.com/photo-1528360983277-13d401cdc186?auto=format&fit=crop&w=800&q=80",
        "best_time_to_visit": "Morning before 9:00 AM"
    },
    {
        "id": "plc-kyo-04",
        "destination": "kyoto",
        "name": "Gion Historic Geisha District & Hanamikoji",
        "category": "Culture & Food",
        "description": "Traditional wooden machiya merchant houses, exclusive ochaya teahouses, and atmospheric lantern-lit cobblestone lanes.",
        "rating": 4.7,
        "estimated_duration_hours": 2.0,
        "estimated_ticket_price": 0.0,
        "image_url": "https://images.unsplash.com/photo-1545569341-9eb8b30979d9?auto=format&fit=crop&w=800&q=80",
        "best_time_to_visit": "Late afternoon and twilight"
    },
    # Paris
    {
        "id": "plc-par-01",
        "destination": "paris",
        "name": "Louvre Museum & Tuileries Garden",
        "category": "Art & History",
        "description": "The world's largest art museum holding historical masterpieces including the Mona Lisa, Venus de Milo, and Winged Victory.",
        "rating": 4.8,
        "estimated_duration_hours": 3.5,
        "estimated_ticket_price": 22.0,
        "image_url": "https://images.unsplash.com/photo-1565099824688-e93eb20fe622?auto=format&fit=crop&w=800&q=80",
        "best_time_to_visit": "Wednesday or Friday evening"
    },
    {
        "id": "plc-par-02",
        "destination": "paris",
        "name": "Eiffel Tower & Champ de Mars",
        "category": "Iconic Landmark",
        "description": "Gustave Eiffel's 1889 wrought-iron monument with breathtaking 360-degree panoramic viewpoints over the Seine.",
        "rating": 4.8,
        "estimated_duration_hours": 2.5,
        "estimated_ticket_price": 30.0,
        "image_url": "https://images.unsplash.com/photo-1502602898657-3e91760cbb34?auto=format&fit=crop&w=800&q=80",
        "best_time_to_visit": "Sunset to catch the hourly sparkle light show"
    },
    # Cairo & Giza
    {
        "id": "plc-cai-01",
        "destination": "cairo",
        "name": "Great Pyramids of Giza & The Sphinx",
        "category": "Ancient Wonder",
        "description": "The last standing wonder of the ancient world built over 4,500 years ago for Pharaoh Khufu, Khafre, and Menkaure.",
        "rating": 4.9,
        "estimated_duration_hours": 4.0,
        "estimated_ticket_price": 18.0,
        "image_url": "https://images.unsplash.com/photo-1503177119275-0aa32b3a9368?auto=format&fit=crop&w=800&q=80",
        "best_time_to_visit": "Morning before peak desert heat"
    },
    {
        "id": "plc-cai-02",
        "destination": "cairo",
        "name": "The Grand Egyptian Museum (GEM)",
        "category": "Museum & Artifacts",
        "description": "The largest archaeological museum in the world, exhibiting the complete Tutankhamun collection and ancient Egyptian antiquities.",
        "rating": 4.9,
        "estimated_duration_hours": 3.5,
        "estimated_ticket_price": 25.0,
        "image_url": "https://images.unsplash.com/photo-1572252009286-268acec5ca0a?auto=format&fit=crop&w=800&q=80",
        "best_time_to_visit": "Early afternoon"
    }
]

def search_places(destination: str) -> PlacesSearchResponse:
    dest_lower = destination.lower()
    matches = [p for p in REAL_PLACES_DB if p["destination"] in dest_lower or (p["destination"] == "cairo" and "egypt" in dest_lower)]
    if not matches:
        matches = [p for p in REAL_PLACES_DB if p["destination"] == "kyoto"]
        
    items = [PlaceItem(**p) for p in matches]
    return PlacesSearchResponse(destination=destination, places=items)
