from fastapi.testclient import TestClient

from web.app import app


client = TestClient(app)


def test_surface_page_returns_ok() -> None:
    response = client.get("/")
    assert response.status_code == 200


def test_setup_page_returns_ok() -> None:
    response = client.get("/setup")
    assert response.status_code == 200


def test_config_page_returns_ok() -> None:
    response = client.get("/config")
    assert response.status_code == 200


def test_logs_page_returns_ok() -> None:
    response = client.get("/logs")
    assert response.status_code == 200
