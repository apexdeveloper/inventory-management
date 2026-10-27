"""
Tests for restocking: demand forecast pricing fields and restock order endpoints.
"""
from datetime import datetime, timedelta

import pytest

import main


@pytest.fixture(autouse=True)
def clear_restock_orders():
    """Restock orders live in a module-level list, so reset it around each test."""
    main.restock_orders.clear()
    yield
    main.restock_orders.clear()


def make_item(sku="WDG-001", quantity=10):
    return {"sku": sku, "quantity": quantity}


class TestDemandForecastPricing:
    """Forecasts must carry the fields the Restocking tab prices against."""

    def test_forecasts_have_cost_and_lead_time(self, client):
        response = client.get("/api/demand")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0
        for forecast in data:
            assert forecast["unit_cost"] > 0
            assert forecast["lead_time_days"] > 0


class TestCreateRestockOrder:
    """Test suite for POST /api/restock-orders."""

    def test_create_returns_computed_order(self, client):
        catalog = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        wdg, gsk = catalog["WDG-001"], catalog["GSK-203"]

        items = [make_item("WDG-001", quantity=10), make_item("GSK-203", quantity=4)]
        response = client.post("/api/restock-orders", json={"items": items})
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert len(order["items"]) == 2
        # Name, price and lead time are filled in from the forecast catalog
        assert order["items"][0]["name"] == wdg["item_name"]
        assert order["items"][0]["unit_cost"] == wdg["unit_cost"]
        assert order["total_value"] == pytest.approx(10 * wdg["unit_cost"] + 4 * gsk["unit_cost"])
        # Order lead time is the slowest item's lead time
        assert order["lead_time_days"] == max(wdg["lead_time_days"], gsk["lead_time_days"])

        submitted = datetime.fromisoformat(order["submitted_date"])
        expected = datetime.fromisoformat(order["expected_delivery"])
        assert expected - submitted == timedelta(days=order["lead_time_days"])

    def test_client_supplied_price_is_ignored(self, client):
        item = {**make_item("WDG-001", quantity=1), "unit_cost": 0.01, "lead_time_days": 0}
        order = client.post("/api/restock-orders", json={"items": [item]}).json()

        assert order["items"][0]["unit_cost"] != 0.01
        assert order["lead_time_days"] > 0

    def test_order_numbers_are_sequential(self, client):
        first = client.post("/api/restock-orders", json={"items": [make_item()]}).json()
        second = client.post("/api/restock-orders", json={"items": [make_item()]}).json()

        assert first["id"] != second["id"]
        assert first["order_number"].endswith("0001")
        assert second["order_number"].endswith("0002")

    def test_empty_items_rejected(self, client):
        response = client.post("/api/restock-orders", json={"items": []})
        assert response.status_code == 400

    def test_zero_quantity_rejected(self, client):
        response = client.post("/api/restock-orders", json={"items": [make_item(quantity=0)]})
        assert response.status_code == 422

    def test_negative_quantity_rejected(self, client):
        response = client.post("/api/restock-orders", json={"items": [make_item(quantity=-5)]})
        assert response.status_code == 422

    def test_unknown_sku_rejected(self, client):
        response = client.post("/api/restock-orders", json={"items": [make_item("NOPE-999")]})
        assert response.status_code == 400
        assert "NOPE-999" in response.json()["detail"]

    def test_duplicate_sku_rejected(self, client):
        items = [make_item("WDG-001"), make_item("WDG-001")]
        response = client.post("/api/restock-orders", json={"items": items})
        assert response.status_code == 400

    def test_missing_fields_rejected(self, client):
        response = client.post("/api/restock-orders", json={"items": [{"quantity": 5}]})
        assert response.status_code == 422


class TestGetRestockOrders:
    """Test suite for GET /api/restock-orders."""

    def test_empty_by_default(self, client):
        response = client.get("/api/restock-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_returns_newest_first(self, client):
        client.post("/api/restock-orders", json={"items": [make_item("WDG-001")]})
        client.post("/api/restock-orders", json={"items": [make_item("GSK-203")]})

        data = client.get("/api/restock-orders").json()
        assert len(data) == 2
        assert data[0]["items"][0]["sku"] == "GSK-203"
        assert data[1]["items"][0]["sku"] == "WDG-001"
