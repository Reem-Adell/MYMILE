# MYMILE Backend Service

FastAPI-powered backend implementing the MYMILE Travel Agent, tool-calling framework, and sponsor integrations.

## Architecture

- **FastAPI Framework:** Clean, modular asynchronous REST API.
- **Pydantic v2:** Robust schema validation for all requests, responses, and tools.
- **AI Agent Suite:**
  - `app/agents/travel_agent.py`: Master planning agent and interactive companion.
  - `app/tools/`: Modular tools for weather, accommodations, landmarks, Channel3 products, and budget optimization.
- **Sponsor Integrations:**
  - **Channel3:** Product search, verified catalog, authentic purchase links.
  - **AG Grid:** Structured data endpoints formatted for AG Grid comparison tables.
  - **APIMatic:** OpenAPI 3.0.3 APIMatic-compliant spec and multi-language SDK endpoints.

## Running Locally

1. Activate virtual environment:
   ```powershell
   .\venv\Scripts\activate
   ```
2. Start development server:
   ```powershell
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
3. Test health check:
   ```powershell
   curl http://127.0.0.1:8000/api/health
   ```
4. Explore interactive documentation at `http://127.0.0.1:8000/docs`.
