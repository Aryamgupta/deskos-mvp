import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import server


class CpuTemperatureSelectionTests(unittest.TestCase):
    def test_prefers_cpu_label_over_earlier_non_cpu_sensor(self):
        readings = [
            {"sensor": "Composite", "celsius": 42.0},
            {"sensor": "CPU", "celsius": 79.0},
            {"sensor": "Tctl", "celsius": 81.0},
        ]

        self.assertEqual(server.select_cpu_temperature(readings), readings[1])

    def test_accepts_common_cpu_sensor_labels(self):
        for label in ("Tctl", "Tdie", "Package id 0"):
            with self.subTest(label=label):
                reading = {"sensor": label, "celsius": 70.0}
                self.assertEqual(server.select_cpu_temperature([reading]), reading)

    def test_returns_none_when_no_sensor_is_identifiably_cpu(self):
        self.assertIsNone(
            server.select_cpu_temperature(
                [{"sensor": "Composite", "celsius": 40.0}, {"sensor": "Ambient", "celsius": 30.0}]
            )
        )


class HttpEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def test_health_get_returns_service_status(self):
        with urlopen(f"{self.base_url}/health") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), {"ok": True, "service": "DeskOS"})

    def test_health_head_returns_success_without_body(self):
        request = Request(f"{self.base_url}/health", method="HEAD")
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertGreater(int(response.headers["Content-Length"]), 0)
            self.assertEqual(response.read(), b"")

    def test_status_includes_monitoring_and_temperature_capabilities(self):
        with urlopen(f"{self.base_url}/api/status") as response:
            self.assertEqual(response.status, 200)
            payload = json.load(response)

        for key in ("hostname", "timestamp", "cpu_percent", "memory", "disk", "network", "temperatures", "cpu_temperature", "capabilities"):
            with self.subTest(key=key):
                self.assertIn(key, payload)
        self.assertEqual(
            payload["capabilities"]["cpu_temperature"],
            payload["cpu_temperature"] is not None,
        )


if __name__ == "__main__":
    unittest.main()
