# api/main.py

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from db.checkpointer import get_checkpointer
from graph.build_graph import build_graph
from api.routers import trips  # will contain create_trip, status, review, itinerary


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    # This 'async with' now wraps the ENTIRE app lifetime, not just one
    # function call - so the connection stays open the whole time the
    # server runs, instead of closing the instant it's opened.
    async with get_checkpointer() as checkpointer:
        await checkpointer.setup()
        compiled_graph = build_graph(checkpointer)

        # stash it somewhere every request can reach
        app.state.graph = compiled_graph

        yield  # <-- app runs here, serving requests, for as long as it's up

    # --- shutdown ---
    # execution resumes here only when the server is stopping;
    # the 'async with' block above closes the connection automatically
    # as control leaves it.


app = FastAPI(title="Waypoint API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000"],  # adjust once frontend origin is known
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trips.router, prefix="/trips")