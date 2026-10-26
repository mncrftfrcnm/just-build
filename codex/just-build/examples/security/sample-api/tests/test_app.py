"""Local-only functionality tests; independent external contract also runs."""
import http.client
import threading
import unittest
from server import Handler, ThreadingHTTPServer

class RateLimitTests(unittest.TestCase):
    def test_quota_independent_clients(self):
        Handler.requests = {}
        service = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=service.serve_forever, daemon=True); worker.start()
        try:
            def check(client):
                connection = http.client.HTTPConnection('127.0.0.1', service.server_address[1], timeout=2)
                try:
                    connection.request('GET','/items',headers={'X-Client-ID':client})
                    response = connection.getresponse(); response.read(); return response.status
                finally:
                    connection.close()
            self.assertEqual([check('a') for _ in range(3)], [200,200,429])
            self.assertEqual(check('b'), 200)
        finally:
            service.shutdown(); service.server_close(); worker.join(timeout=2)
