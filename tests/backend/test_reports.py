"""
Tests for reports API endpoints.
"""
import pytest


QUARTER_MONTHS = {
    "Q1-2025": ["2025-01", "2025-02", "2025-03"],
    "Q2-2025": ["2025-04", "2025-05", "2025-06"],
    "Q3-2025": ["2025-07", "2025-08", "2025-09"],
    "Q4-2025": ["2025-10", "2025-11", "2025-12"],
}


def orders_for(client, query=""):
    """Orders matching the same filters, for cross-checking report totals."""
    response = client.get(f"/api/orders{query}")
    assert response.status_code == 200
    return response.json()


class TestQuarterlyReports:
    """Test suite for /api/reports/quarterly."""

    def test_get_quarterly_reports(self, client):
        """Test getting quarterly reports without filters."""
        response = client.get("/api/reports/quarterly")
        assert response.status_code == 200

        data = response.json()
        assert [q["quarter"] for q in data] == list(QUARTER_MONTHS)

        for quarter in data:
            for field in ("quarter", "total_orders", "total_revenue", "delivered_orders",
                          "avg_order_value", "fulfillment_rate"):
                assert field in quarter
            assert isinstance(quarter["total_orders"], int)
            assert isinstance(quarter["total_revenue"], (int, float))
            assert 0 <= quarter["fulfillment_rate"] <= 100

    def test_quarterly_totals_match_orders(self, client):
        """Test that quarterly order counts and revenue add up to all orders."""
        data = client.get("/api/reports/quarterly").json()
        all_orders = orders_for(client)

        assert sum(q["total_orders"] for q in data) == len(all_orders)
        assert abs(sum(q["total_revenue"] for q in data) - sum(o["total_value"] for o in all_orders)) < 0.01

    def test_quarterly_calculations(self, client):
        """Test average order value and fulfillment rate for each quarter."""
        all_orders = orders_for(client)

        for quarter in client.get("/api/reports/quarterly").json():
            in_quarter = [o for o in all_orders if o["order_date"][:7] in QUARTER_MONTHS[quarter["quarter"]]]
            delivered = sum(1 for o in in_quarter if o["status"] == "Delivered")

            assert quarter["total_orders"] == len(in_quarter)
            assert quarter["delivered_orders"] == delivered
            assert abs(quarter["avg_order_value"] - quarter["total_revenue"] / len(in_quarter)) < 0.01
            assert abs(quarter["fulfillment_rate"] - round(delivered / len(in_quarter) * 100, 1)) < 0.01

    @pytest.mark.parametrize("query", [
        "?warehouse=Tokyo",
        "?category=Sensors",
        "?status=Delivered",
        "?month=2025-02",
        "?warehouse=London&category=Sensors&status=Shipped",
    ])
    def test_get_quarterly_reports_filtered(self, client, query):
        """Test that each filter, alone and combined, matches the filtered orders."""
        response = client.get(f"/api/reports/quarterly{query}")
        assert response.status_code == 200

        data = response.json()
        filtered = orders_for(client, query)

        assert sum(q["total_orders"] for q in data) == len(filtered)
        assert abs(sum(q["total_revenue"] for q in data) - sum(o["total_value"] for o in filtered)) < 0.01

    def test_quarterly_reports_month_filter_keeps_one_quarter(self, client):
        """Test that a single-month filter only returns that month's quarter."""
        data = client.get("/api/reports/quarterly?month=2025-05").json()
        assert [q["quarter"] for q in data] == ["Q2-2025"]

    def test_quarterly_reports_all_filter_values(self, client):
        """Test that 'all' filter values return the unfiltered report."""
        unfiltered = client.get("/api/reports/quarterly").json()
        response = client.get("/api/reports/quarterly?warehouse=all&category=all&status=all&month=all")
        assert response.json() == unfiltered

    def test_quarterly_reports_no_matches(self, client):
        """Test that filters matching no orders return an empty list."""
        response = client.get("/api/reports/quarterly?warehouse=Nowhere")
        assert response.status_code == 200
        assert response.json() == []


class TestMonthlyTrends:
    """Test suite for /api/reports/monthly-trends."""

    def test_get_monthly_trends(self, client):
        """Test getting monthly trends without filters."""
        response = client.get("/api/reports/monthly-trends")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 12
        months = [m["month"] for m in data]
        assert months == sorted(months)

        for month in data:
            for field in ("month", "order_count", "revenue", "delivered_count"):
                assert field in month
            assert isinstance(month["order_count"], int)
            assert month["delivered_count"] <= month["order_count"]

    def test_monthly_trends_match_orders(self, client):
        """Test that each month's count and revenue match the orders placed that month."""
        all_orders = orders_for(client)

        for month in client.get("/api/reports/monthly-trends").json():
            in_month = [o for o in all_orders if o["order_date"].startswith(month["month"])]
            assert month["order_count"] == len(in_month)
            assert abs(month["revenue"] - sum(o["total_value"] for o in in_month)) < 0.01

    @pytest.mark.parametrize("query", [
        "?warehouse=San Francisco",
        "?category=Circuit Boards",
        "?status=Backordered",
        "?month=2025-07",
        "?warehouse=Tokyo&category=Sensors&status=Delivered",
    ])
    def test_get_monthly_trends_filtered(self, client, query):
        """Test that each filter, alone and combined, matches the filtered orders."""
        response = client.get(f"/api/reports/monthly-trends{query}")
        assert response.status_code == 200

        data = response.json()
        filtered = orders_for(client, query)

        assert sum(m["order_count"] for m in data) == len(filtered)
        assert abs(sum(m["revenue"] for m in data) - sum(o["total_value"] for o in filtered)) < 0.01

    def test_monthly_trends_month_filter(self, client):
        """Test that a month filter returns only that month."""
        data = client.get("/api/reports/monthly-trends?month=2025-03").json()
        assert [m["month"] for m in data] == ["2025-03"]

    def test_monthly_trends_no_matches(self, client):
        """Test that filters matching no orders return an empty list."""
        response = client.get("/api/reports/monthly-trends?category=Nothing")
        assert response.status_code == 200
        assert response.json() == []
