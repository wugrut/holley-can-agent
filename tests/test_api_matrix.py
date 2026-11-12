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

        hist_res = client.get("/api/optimizer/history").json()
        assert hist_res["status"] == "success"
        assert isinstance(hist_res["history"], list)

        rev_res = client.post("/api/optimizer/revert", json={"id": "nonexistent"}).json()
        assert rev_res["status"] == "error"

        # Test TERX discover API
        disc_res = client.get("/api/terx/discover").json()
        assert disc_res["status"] == "success"
        assert "calibrations" in disc_res
        assert isinstance(disc_res["calibrations"], list)

        # Test Channels Catalog API for customizable live dashboard
        cat_res = client.get("/api/channels/catalog")
        assert cat_res.status_code == 200
        cat_data = cat_res.json()
        assert cat_data["total"] == 86
        assert len(cat_data["channels"]) == 86
        names = [ch["name"] for ch in cat_data["channels"]]
        assert "rpm" in names
        assert "boost_psig" in names
        assert "fuel_pressure" in names
        assert "knock_retard" in names
        assert "trans_temp" in names
