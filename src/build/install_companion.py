#!/usr/bin/env python3
# ==============================================================================
# GDC Installation Companion & Webhook Log Receiver
# ==============================================================================
# A zero-dependency, lightweight HTTP server that receives Subiquity automated 
# webhook logs and formats them into a clean, human-readable terminal output.
# Saves all logs to 'gdc-installer-receiver.log' for deep debugging.
# ==============================================================================

import os
import sys
import json
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Terminal Color Codes for Beautiful Formatting
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class SubiquityLogHandler(BaseHTTPRequestHandler):
    log_file_path = "gdc-installer-receiver.log"

    def log_message(self, format, *args):
        # Suppress standard HTTP request logging to keep the console clean
        return

    def do_POST(self):
        # Send instant response back to Subiquity to prevent blocking the installer
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"status":"received"}')

        # Read POST content length and payload
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)

        # Parse Client Common Name (CN) from header or fallback to query parameter
        client_cn = self.headers.get('X-Client-Cert-CN', '')
        if not client_cn and '?' in self.path:
            try:
                from urllib.parse import parse_qs, urlparse
                query = urlparse(self.path).query
                params = parse_qs(query)
                client_cn = params.get('client_cert_cn', [''])[0]
            except Exception:
                pass

        try:
            payload = json.loads(post_data.decode('utf-8'))
            self.process_webhook_payload(payload, client_cn)
        except Exception as e:
            # Handle non-JSON or raw text data gracefully
            raw_text = post_data.decode('utf-8', errors='ignore')
            self.log_and_print_raw(raw_text, client_cn)

    def process_webhook_payload(self, payload, client_cn=""):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Subiquity reporting webhooks can send different event types
        event_type = payload.get("type", "unknown")
        level = payload.get("level", "INFO").upper()
        msg = payload.get("description", payload.get("message", ""))
        
        # Fallback payload formats (e.g. cloud-init / general webhooks)
        if not msg and "data" in payload:
            msg = str(payload["data"])
            
        status = payload.get("status", "").upper()
        
        # Format terminal message based on status/event
        color = Colors.ENDC
        prefix = "[INFO]"
        
        if "FAIL" in status or level == "ERROR" or "CRITICAL" in msg.upper() or "FAIL" in msg.upper():
            color = Colors.FAIL + Colors.BOLD
            prefix = "[GDC-INSTALL-FAIL]"
        elif "SUCCESS" in status or "COMPLETE" in msg.upper():
            color = Colors.OKGREEN + Colors.BOLD
            prefix = "[GDC-INSTALL-SUCCESS]"
        elif "RUNNING" in status or "START" in msg.upper():
            color = Colors.OKCYAN
            prefix = "[GDC-INSTALL-GOAL]"
        elif level == "WARNING":
            color = Colors.WARNING
            prefix = "[WARNING]"

        # Extract structured task information if present
        task_name = payload.get("name", "")
        task_info = f" (Task: {task_name})" if task_name else ""
        client_info = f" [{client_cn}]" if client_cn else ""

        formatted_msg = f"{color}{prefix} {timestamp}{client_info}{task_info} | {msg}{Colors.ENDC}"
        print(formatted_msg)
        sys.stdout.flush()

        # Write clean and raw data to local persistent file
        with open(self.log_file_path, "a") as f:
            f.write(f"[{timestamp}] [{level}] [{status}]{client_info} {task_name} - {msg}\n")
            # If payload contains deep log/stdout detail, dump it to file
            if "log" in payload or "stdout" in payload or "stderr" in payload:
                detail = payload.get("log", payload.get("stdout", payload.get("stderr", "")))
                f.write(f"--- DETAIL ---\n{detail}\n--------------\n")

    def log_and_print_raw(self, text, client_cn=""):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        client_info = f" [{client_cn}]" if client_cn else ""
        print(f"{Colors.OKBLUE}[RAW PAYLOAD] {timestamp}{client_info} | {text}{Colors.ENDC}")
        sys.stdout.flush()
        with open(self.log_file_path, "a") as f:
            f.write(f"[{timestamp}] [RAW]{client_info} {text}\n")

def run_server(port):
    print("==============================================================================")
    print(f" {Colors.OKGREEN}{Colors.BOLD}GDC DISK PROVISIONER - INSTALLATION COMPANION LOG RECEIVER{Colors.ENDC} ")
    print("==============================================================================")
    print(f"  [-] Status:          {Colors.BOLD}Listening for logs...{Colors.ENDC}")
    print(f"  [-] Local Address:   http://0.0.0.0:{port}/v1/install-logs")
    print(f"  [-] Log File Target: {os.path.abspath(SubiquityLogHandler.log_file_path)}")
    print("==============================================================================")
    print("  * Boot your bare metal machine with the GDC custom ISO.")
    print("  * Enforce that your user-data webhook points to this server's IP.")
    print("  * Logs, goals, and failure signals will stream live below:")
    print("==============================================================================")
    print("")
    sys.stdout.flush()

    server_address = ('', port)
    httpd = HTTPServer(server_address, SubiquityLogHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}[-] Server stopped by operator.{Colors.ENDC}")
        sys.exit(0)

if __name__ == "__main__":
    # REMOVE ME BEFORE PRODUCTION: Defaulting to local dev port 8080. Update to 80/443 for production.
    port = 8080
    clean_log = False
    
    if "--clean" in sys.argv:
        clean_log = True
        sys.argv.remove("--clean")
        
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"[!] Error: Invalid port '{sys.argv[1]}'. Defauting to 8080.")
            
    if clean_log:
        log_file_path = SubiquityLogHandler.log_file_path
        if os.path.exists(log_file_path):
            try:
                os.remove(log_file_path)
                print(f"[-] Option --clean active: Fresh copy started. Removed '{os.path.abspath(log_file_path)}'")
            except Exception as e:
                print(f"[!] Warning: Failed to remove log file '{log_file_path}': {e}")
                
    run_server(port)
