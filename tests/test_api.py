import pytest
from httpx import AsyncClient, ASGITransport
import uuid
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../api')))

from main import app

import pytest_asyncio

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded", "unhealthy"]
    assert "model_loaded" in data

@pytest.mark.asyncio
async def test_moderate_toxic(client):
    response = await client.post("/moderate", json={"comment": "I hate everyone"})
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["label"] == "toxic"

@pytest.mark.asyncio
async def test_moderate_clean(client):
    response = await client.post("/moderate", json={"comment": "Great weather today!"})
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["label"] == "non_toxic"

@pytest.mark.asyncio
async def test_moderate_empty_comment(client):
    response = await client.post("/moderate", json={"comment": ""})
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_moderate_too_long(client):
    response = await client.post("/moderate", json={"comment": "a" * 5001})
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_response_has_request_id(client):
    response = await client.post("/moderate", json={"comment": "Test"})
    assert response.status_code == 200
    data = response.json()
    # Check if request_id is valid UUID string
    try:
        uuid_obj = uuid.UUID(data["request_id"], version=4)
    except ValueError:
        pytest.fail("request_id is not a valid UUID4")

@pytest.mark.asyncio
async def test_process_time_header(client):
    response = await client.post("/moderate", json={"comment": "Test"})
    assert response.status_code == 200
    assert "x-process-time-ms" in response.headers
