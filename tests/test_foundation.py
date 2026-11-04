from unittest.mock import patch

from django.db import OperationalError, connection
from django.test import TestCase


class FoundationPages(TestCase):
    def test_home_renders_the_base_layout(self):
        response = self.client.get("/")
        self.assertContains(response, '<meta name="viewport"')
        self.assertContains(response, "Skip to content")
        self.assertContains(response, 'id="main"')
        self.assertEqual(self.client.post("/").status_code, 405)

    def test_liveness_and_missing_page(self):
        self.assertJSONEqual(self.client.get("/healthz").content, {"status": "ok"})
        self.assertContains(self.client.get("/missing/"), "could not be found", status_code=404)

    def test_readiness_reports_failure_without_exposing_details(self):
        with patch("storefront.views.connection") as database:
            database.cursor.side_effect = OperationalError("sensitive")
            with self.assertLogs("storefront.views", "WARNING") as log:
                response = self.client.get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertJSONEqual(response.content, {"status": "unavailable"})
        self.assertNotIn("sensitive", "\n".join(log.output))


class DatabaseReadiness(TestCase):
    def test_readiness_checks_postgresql(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertJSONEqual(self.client.get("/readyz").content, {"status": "ready"})
