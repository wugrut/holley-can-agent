from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from holley_can.agent_api import DashboardBroadcaster, create_app


def _make_app():
    listener = MagicMock()
    listener._running = True
    listener.start = AsyncMock()
    listener.stop = AsyncMock()
    storage = AsyncMock()
    return create_app(listener, storage, DashboardBroadcaster())


def test_matrix_endpoint_serves_ui_contract():
    with TestClient(_make_app()) as client:
        r = client.get("/api/optimizer/matrix")
        assert r.status_code == 200
        data = r.json()
        assert len(data["rows"]) == 16
        # Alert/comparison fields must always be present (content depends on any logs found on disk)
        assert isinstance(data["safety_alerts"], list)
        assert data["safety_level"] in ("info", "warning", "critical")
        assert "pull_comparison" in data and "comparison" in data
        assert "holley_tsv_ve" in data

        assert client.get("/").status_code == 200
        reset = client.post("/api/optimizer/reset").json()
        assert reset["status"] == "success"
        assert reset["matrix"]["safety_alerts"] == []
