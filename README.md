# Waypoint

**Every Great Journey Starts with a Waypoint.**

Waypoint is a multi-agent trip planner for domestic travel in India. You describe a trip (destination, dates, party size, budget, interests, pace) and a LangGraph pipeline searches flights, trains, hotels, activities and weather, checks the plan against your budget, and builds a day-by-day itinerary. You then refine it through a chat-based review loop before approving it.

Built with LangGraph, FastAPI, PostgreSQL and Groq-hosted open-weight models (`gpt-oss-20b`, `gpt-oss-120b`).

---

## Features

- **Real data, not guesses.** Live flights, train fares, hotels, activities and a 16-day weather forecast feed the itinerary. The builder only schedules options the tools actually returned.
- **Group-aware budgeting.** Flight, train and hotel costs are all computed for the full party, so totals are comparable across modes.
- **Review loop.** Ask for changes in plain language ("make it cheaper", "switch to trains"). The Critic updates the trip parameters and re-runs only what needs to change.
- **Crash recovery.** State is checkpointed in Postgres at every node boundary. If a run fails midway, `POST /trips/{trip_id}/resume` continues from the failed node without repeating API calls.
- **Calendar export.** Download the finalized itinerary as an `.ics` file for Google Calendar, Apple Calendar or Outlook.
- **No build step on the frontend.** Vanilla HTML/CSS/JS with Leaflet maps and a timeline view.

---

## Architecture

```mermaid
flowchart TD
    U([Trip form]) --> C[Concierge<br/>deterministic]
    C --> P[Planner<br/>gpt-oss-20b]

    P --> F[search_flights]
    P --> T[search_trains]
    P --> H[search_hotels]
    P --> A[search_activities]
    P --> W[get_weather]

    F --> B[Budget<br/>gpt-oss-20b]
    T --> B
    H --> B
    A --> B
    W --> B

    B --> I[Itinerary Builder<br/>gpt-oss-120b]
    I --> V[Validator<br/>deterministic]
    V --> R{human_review<br/>interrupt}

    R -- approved --> Z[Finalize]
    R -- edit requested --> K[Critic<br/>gpt-oss-120b]
    K -- targeted re-run --> P
```

### Pipeline stages

| Stage | Type | What it does |
|---|---|---|
| **Concierge** | Python, no LLM | Normalizes form input into canonical values (e.g. `"Mumbai, India"`) and enforces a 7-day maximum trip length. Zero tokens, zero latency. |
| **Planner** | LLM (20B) | Chooses transport modes and a budget tier (`tight`, `balanced`, `luxury`) and parameterizes the tool nodes. |
| **Tool nodes** | Python | Fetch flights, trains, hotels, activities and weather in parallel. Mechanical, no LLM reasoning. |
| **Budget** | LLM (20B) | Compares group transport cost against stay and activity costs to set a conservative feasibility floor. |
| **Itinerary Builder** | LLM (120B) | Turns tool results into a day-by-day schedule. Handles arrival-day check-ins, pace density and real place names. |
| **Validator** | Python, no LLM | Sorts events chronologically and recomputes all cost totals, so the LLM never does the arithmetic. |
| **human_review** | LangGraph `interrupt()` | Pauses the graph and waits for approval or edit feedback. The session survives a browser refresh. |
| **Critic** | LLM (120B) | Interprets feedback and routes to the node that needs to re-run, not a full replan. |

### Design decisions

- **Deterministic where possible.** Normalization and validation are plain Python. LLMs are used only where judgment or composition is needed.
- **Two model tiers.** The 20B model handles planning and budgeting; the 120B model is reserved for scheduling and revision interpretation. Reasoning effort is set to `low` and output tokens are capped to keep within Groq's 8,000 TPM free-tier limit.
- **Token discipline.** Candidate payloads are pruned by roughly 65% before reaching the builder, and requests are paced dynamically based on token usage instead of fixed sleeps.
- **Fail loud.** Tool nodes return structured diagnostic notes on failure rather than silent empty lists, so problems are visible downstream.
- **Typed outputs.** All LLM calls use JSON-schema structured output with Pydantic models.
- **Stable graph, swappable tools.** Each data source follows the same staging: dummy data, then a free or paid API, then MCP. Changing a tool's implementation never changes graph wiring.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12, managed with `uv` |
| API | FastAPI (async) |
| Orchestration | LangGraph + LangChain |
| Validation | Pydantic v2 |
| LLMs | Groq: `openai/gpt-oss-20b`, `openai/gpt-oss-120b` |
| Database | PostgreSQL, SQLAlchemy 2.0, Alembic |
| Checkpointing | `langgraph-checkpoint-postgres` |
| Retries | Tenacity (exponential backoff on all external calls) |
| Frontend | Vanilla HTML/CSS/JS, Leaflet, CartoDB Dark Matter tiles, Satoshi font |

### Data sources

| Data | Provider | Notes |
|---|---|---|
| Flights | SerpApi (Google Flights) | Strict IATA validation before each request to avoid 400 errors; aggregate group pricing. |
| Trains | RailRadar | Indian Railways schedules and fares; city-to-station mapping (e.g. Mumbai to BCT/CSMT); group fares; autocomplete fallback with caching and a 429 circuit breaker. |
| Hotels | SerpApi (Google Hotels) | Location and budget-tier filtering. |
| Activities | Tavily + LLM | Basic search results merged, deduplicated, then extracted into discrete activities. |
| Weather | Open-Meteo | 16-day live forecast; two-tier geocoding for Indian states; seasonal estimate beyond the forecast horizon. |
| Buses, rental cars | Deferred | Stubs are in place; not used by the Planner in the current version. |

---

## Getting Started

### Prerequisites

- Python 3.12 and [`uv`](https://docs.astral.sh/uv/)
- Docker (for PostgreSQL)
- API keys: [Groq](https://console.groq.com/), [SerpApi](https://serpapi.com/), [Tavily](https://tavily.com/), RailRadar

### Setup

```bash
git clone https://github.com/harshbhanushali26/waypoint.git
cd waypoint
uv sync
```

Create a `.env` file in the project root:

```env
GROQ_API_KEY=
SERPAPI_API_KEY=
TAVILY_API_KEY=
RAILRADAR_API_KEY=

DATABASE_URL=postgresql://postgres:postgres@localhost:5432/waypoint
```

Start Postgres:

```bash
docker run --name waypoint-postgres \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=waypoint \
  -p 5432:5432 -d postgres:16-alpine
```

Run migrations, then start the API:

```bash
uv run alembic upgrade head
uv run uvicorn api.main:app --reload --port 8000
```

Serve the frontend in a second terminal:

```bash
python -m http.server 5500 --directory frontend
```

Open `http://localhost:5500/landing.html`.

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/trips` | Start a trip from the form payload |
| `GET` | `/trips/{trip_id}` | Poll status and fetch the itinerary |
| `POST` | `/trips/{trip_id}/review` | Submit approval or edit feedback |
| `POST` | `/trips/{trip_id}/resume` | Resume a failed run from its last checkpoint |

Interactive docs are available at `http://localhost:8000/docs` while the server is running.

---

## Testing

The test suites run fully offline: no API calls, no cost.

```bash
# Full suite
uv run pytest -v

# Chaos suite (CS-01 to CS-07, about 1.3 seconds)
uv run pytest tests/test_chaos_evaluation.py -v -s

# Fixture evaluation suite (TC-01 to TC-06)
uv run python -m tests.test_evaluation_fixtures
```

**Chaos scenarios** cover tool outages, budget starvation, midnight rollovers in schedules, and prompt-injection attempts in review feedback.

**Fixture cases** check grounding (only tool-returned options appear in the plan), chronological ordering, and exact budget math.

---

## Roadmap

- Bus search (`search_buses`) via Indian booking aggregators
- Rental car search (`search_cars`)
- MCP servers for the tool layer
- Component-level edits in review mode ("keep the hotel, upgrade the train to 2nd AC")
- Trip history and user accounts

---

## License

MIT