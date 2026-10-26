"""Minimal local API fixture for testing, NOT a production server."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
import threading

class Handler(BaseHTTPRequestHandler):
    requests = {}
    limit = 2
    window = 0.5
    lock = threading.Lock()

    def do_GET(self):
        if self.path == '/health':
            return self.reply(200, {'status': 'ready'})
        if self.path == '/bad':
            return self.reply(400, {'error': 'invalid request'})
        if self.path != '/items':
            return self.reply(404, {'error': 'not found'})
        client = self.headers.get('X-Client-ID', 'anonymous')
        now = time.monotonic()
        with self.lock:  # Sample's threaded server must decide quota atomically.
            history = [t for t in self.requests.get(client, []) if now-t < self.window]
            limited = len(history) >= self.limit
            if not limited:
                history.append(now)
            self.requests[client] = history
        if limited:
            return self.reply(429, {'error': 'rate limit exceeded'}, {'Retry-After': '1'})
        return self.reply(200, {'items': []})

    def reply(self, code, obj, headers=None):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for key,value in (headers or {}).items():
            self.send_header(key,value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, required=True)
    args = p.parse_args()
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
