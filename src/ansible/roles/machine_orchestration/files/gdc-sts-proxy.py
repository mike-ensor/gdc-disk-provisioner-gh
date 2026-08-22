from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class STSProxy(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/token":
            try:
                with open("/run/gdc-auth/access_token", "r") as f:
                    token = f.read().strip()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "access_token": token,
                    "issued_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "token_type": "Bearer",
                    "expires_in": 3599
                }).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

try:
    HTTPServer(("127.0.0.1", 12345), STSProxy).serve_forever()
except Exception as e:
    pass
