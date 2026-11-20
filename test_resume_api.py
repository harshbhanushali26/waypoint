"""
test_resume_api.py
Verifies the POST /trips/{trip_id}/resume API logic and checkpoint continuation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routers.trips import router

app = FastAPI()
app.include_router(router, prefix="/trips")

def test_resume_endpoint_with_pending_nodes():
    client = TestClient(app)
    
    # 1. Setup mock graph with a state snapshot paused at 'itinerary_builder'
    mock_graph = MagicMock()
    mock_snapshot = MagicMock()
    mock_snapshot.values = {"status": "planning", "flights": ["6E-101"]}
    mock_snapshot.next = ("itinerary_builder",)
    
    mock_graph.aget_state = AsyncMock(return_value=mock_snapshot)
    mock_graph.ainvoke = AsyncMock()
    
    app.state.graph = mock_graph
    
    # 2. Call resume endpoint
    response = client.post("/trips/test-trip-uuid/resume")
    
    assert response.status_code == 200
    data = response.json()
    assert data["resumed"] is True
    assert data["resuming_from_node"] == ["itinerary_builder"]
    print("✅ Resume Endpoint (Active Checkpoint): Successfully triggered resumption for node 'itinerary_builder'")


def test_resume_endpoint_with_completed_trip():
    client = TestClient(app)
    
    # Setup mock graph for already completed trip (no next nodes)
    mock_graph = MagicMock()
    mock_snapshot = MagicMock()
    mock_snapshot.values = {"status": "completed"}
    mock_snapshot.next = ()
    
    mock_graph.aget_state = AsyncMock(return_value=mock_snapshot)
    app.state.graph = mock_graph
    
    response = client.post("/trips/completed-trip-uuid/resume")
    assert response.status_code == 200
    data = response.json()
    assert data["resumed"] is False
    assert "already at a terminal state" in data["message"]
    print("✅ Resume Endpoint (Terminal State Guard): Gracefully rejected redundant resumption")


if __name__ == "__main__":
    print("\n🚀 VERIFYING RESUME API ENDPOINT...\n")
    test_resume_endpoint_with_pending_nodes()
    test_resume_endpoint_with_completed_trip()
    print("\n🎉 ALL RESUME API CHECKS PASSED!\n")