#!/bin/sh
set -e

# Minimal HTTP health-check server so Cloud Run's liveness probe passes.
# Celery does not bind a port; Cloud Run requires one.
python -c "
import http.server, os, threading

class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'ok')
    def log_message(self, *args):
        pass

port = int(os.environ.get('PORT', 8080))
server = http.server.HTTPServer(('0.0.0.0', port), HealthHandler)
t = threading.Thread(target=server.serve_forever, daemon=True)
t.start()
" &

exec celery -A config worker -l info
