"""
Product planning from three sources: trip purpose (primary), destination weather (primary:
the live forecast for the trip days, else the season) and the optional notes (context, not a
shopping list). Covers the five scenarios of the 2026-11-12 request.

Run from backend/:
    venv\\Scripts\\python -m unittest tests.test_trip_context_products -v
No real Groq, Channel3 or weather requests.
"""
from tests import _env  # noqa: F401  (must precede any app.* import)

import json
import unittest
from contextlib import contextmanager
from unittest import mock

from app.agents import tools, travel_agent
from app.schemas.weather_schema import WeatherForecastDay, WeatherResponse
from app.services import trip_shopping
from tests._fake_groq import FakeGroq, calls, text
from tests.test_channel3 import FakeChannel3, ok
from tests.test_gemini_agent import plan_json
from tests.test_trip_products import _ProductsApi, prompt_parts

LIVE = "Open-Meteo Live API"
BASELINE = "Open-Meteo Baseline Meteorological Cache"


def weather(dest, lat, lon, source=BASELINE, days=()):
    forecast = [WeatherForecastDay(date=d, condition=c, temp_min_c=lo, temp_max_c=hi, temp_min_f=0, temp_max_f=0,
                                   precipitation_prob=rain) for d, c, lo, hi, rain in days]
    return WeatherResponse(destination=dest, latitude=lat, longitude=lon, current_temp_c=10, current_condition="x",
                           packing_tip="", forecast=forecast, source=source)


LONDON = weather("London, United Kingdom", 51.51, -0.13)
ISTANBUL = weather("Istanbul, Turkey", 41.01, 28.98)
MAKKAH = weather("Makkah, Saudi Arabia", 21.42, 39.83)


class WeatherContextTest(unittest.TestCase):

    def test_live_forecast_for_the_trip_days_is_used(self):
        w = weather("London", 51.5, -0.1, LIVE, [("2026-12-07", "Light rain", 3, 8, 80), ("2026-12-08", "Overcast", 2, 7, 30),
                                                 ("2026-12-20", "Sunny", 20, 31, 0)])
        ctx = trip_shopping.weather_context(w, "2026-12-07", "2026-12-11")
        self.assertEqual(ctx, {"basis": "forecast", "conditions": ["cold", "wet"], "temp_c": [2, 8], "max_rain_chance": 80},
                         "only days inside the trip count (the sunny Dec 20 is ignored)")

    def test_forecast_outside_the_trip_falls_back_to_the_season(self):
        w = weather("London", 51.5, -0.1, LIVE, [("2026-11-12", "Sunny", 12, 16, 0)])
        self.assertEqual(trip_shopping.weather_context(w, "2026-12-07", "2026-12-11"),
                         {"basis": "seasonal", "conditions": ["cold", "wet"]})

    def test_the_offline_baseline_is_never_treated_as_a_forecast(self):
        w = weather("London", 51.5, -0.1, BASELINE, [("2026-12-07", "Sunny", 20, 31, 0)])
        self.assertEqual(trip_shopping.weather_context(w, "2026-12-07", "2026-12-11")["basis"], "seasonal")

    def test_unknown_coordinates_give_no_weather_needs(self):
        w = weather("Atlantis", 35.0116, 135.7681)  # the geocoder's fallback, not Atlantis
        self.assertIsNone(trip_shopping.weather_context(w, "2026-12-07", "2026-12-11"))
        self.assertIsNone(trip_shopping.weather_context(None, "2026-12-07", "2026-12-11"))

    def test_seasons(self):
        season = trip_shopping._season_conditions
        self.assertEqual(season(51.5, ["July"]), [])
        self.assertEqual(season(-33.9, ["July"]), ["cool"], "southern winter at Cape Town / Sydney latitude")
        self.assertEqual(season(-41.3, ["July"]), ["cold", "wet"])
        self.assertEqual(season(25.2, ["July"]), ["hot"], "Dubai summer")
        self.assertEqual(season(1.3, ["January"]), ["hot"], "tropics")


if __name__ == "__main__":
    unittest.main()
