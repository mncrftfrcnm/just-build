import http.client
import threading
import unittest
from server import Handler, ThreadingHTTPServer

class InputTests(unittest.TestCase):
    def test_invalid_route_reports_4xx(self):
        service = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=service.serve_forever, daemon=True); worker.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', service.server_address[1], timeout=2)
            connection.request('GET','/bad'); response = connection.getresponse(); raw = response.read().decode(); connection.close()
            self.assertEqual(response.status, 400)
            self.assertIn('invalid request',raw)
        finally:
            service.shutdown(); service.server_close(); worker.join(timeout=2)
