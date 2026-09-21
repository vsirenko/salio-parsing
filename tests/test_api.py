import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_product_service
from app.main import app
from app.services.products import ProductService


@pytest.fixture
def client():
    # One fresh in-memory service per test, shared by every request in that test.
    service = ProductService()
    app.dependency_overrides[get_product_service] = lambda: service
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_products(client):
    response = client.get("/api/products", params={"limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3


def test_create_product(client):
    response = client.post("/api/products", json={"name": "Grinder", "price": 129.9})
    assert response.status_code == 201
    assert response.json()["id"] > 0


def test_create_product_conflict(client):
    client.post("/api/products", json={"name": "Grinder", "price": 129.9})
    response = client.post("/api/products", json={"name": "grinder", "price": 10})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_validation_error(client):
    response = client.post("/api/products", json={"name": "", "price": -5})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_not_found(client):
    response = client.get("/api/products/9999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
