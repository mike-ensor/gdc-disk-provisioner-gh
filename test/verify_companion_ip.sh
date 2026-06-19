#!/usr/bin/env bash
# ==============================================================================
# GDC Installation Companion IP Verification Tool
# ==============================================================================
# Inspects 'src/build/build.env' for the configured INSTALL_COMPANION_URL,
# compares the target IP against the host's active network interfaces,
# and verifies if the companion log receiver is running and reachable.
# ==============================================================================

set -euo pipefail

# Determine script paths and move to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# Color Codes for beautiful logging
RED='\033[91m'
GREEN='\033[92m'
YELLOW='\033[93m'
CYAN='\033[96m'
BOLD='\033[1m'
NC='\033[0m'

echo "=============================================================================="
echo -e "${CYAN}${BOLD}GDC INSTALLATION COMPANION - IP & REACHABILITY VERIFIER${NC}"
echo "=============================================================================="

# 1. Read build.env configurations
ENV_FILE="${PROJECT_ROOT}/src/build/build.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    echo -e "${RED}[!] Error: Centralized variables file not found at ${ENV_FILE}${NC}" >&2
    exit 1
fi

# Extract INSTALL_COMPANION_URL
COMPANION_URL=$(grep "^INSTALL_COMPANION_URL=" "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"'\')

if [[ -z "${COMPANION_URL}" ]]; then
    echo -e "${RED}[!] Error: INSTALL_COMPANION_URL is not defined in ${ENV_FILE}${NC}" >&2
    exit 1
fi

echo -e "[-] Configured Companion URL:   ${BOLD}${COMPANION_URL}${NC}"

# Parse Host and Port from URL (e.g. http://192.168.10.1:8080/v1/install-logs)
# Using python standard library to parse URL components robustly
PARSED_JSON=$(python3 -c "
import urllib.parse, json
parsed = urllib.parse.urlparse('${COMPANION_URL}')
print(json.dumps({
    'host': parsed.hostname or '',
    'port': parsed.port or 80,
    'path': parsed.path or '/'
}))
")

COMPANION_HOST=$(echo "${PARSED_JSON}" | python3 -c "import json, sys; print(json.load(sys.stdin)['host'])")
COMPANION_PORT=$(echo "${PARSED_JSON}" | python3 -c "import json, sys; print(json.load(sys.stdin)['port'])")

# Resolve hostname to IP if it is a DNS name
RESOLVED_IP=$(python3 -c "
import socket
try:
    print(socket.gethostbyname('${COMPANION_HOST}'))
except Exception:
    print('')
")

if [[ -n "${RESOLVED_IP}" && "${RESOLVED_IP}" != "${COMPANION_HOST}" ]]; then
    echo -e "[-] Resolved DNS Host to IP:   ${BOLD}${RESOLVED_IP}${NC}"
fi

echo -e "[-] Parsed Target IP/Host:     ${BOLD}${COMPANION_HOST}${NC}"
echo -e "[-] Parsed Target Port:        ${BOLD}${COMPANION_PORT}${NC}"

# 2. Check if the parsed IP matches any active host interfaces
echo -e "[-] Checking active host network interfaces..."
HOST_IPS=($(ip -o addr show | awk '{print $4}' | cut -d'/' -f1))

IP_MATCHED=false
for ip in "${HOST_IPS[@]}"; do
    if [[ "${ip}" == "${COMPANION_HOST}" || "${ip}" == "${RESOLVED_IP}" ]]; then
        IP_MATCHED=true
        break
    fi
done

# If the target host is loopback or localhost, it's matched
if [[ "${COMPANION_HOST}" == "localhost" || "${COMPANION_HOST}" == "127.0.0.1" ]]; then
    IP_MATCHED=true
fi

if [[ "${IP_MATCHED}" == "true" ]]; then
    echo -e "${GREEN}[x] SUCCESS: Target IP '${COMPANION_HOST}' matches an active host interface!${NC}"
else
    echo -e "${RED}[!] WARNING: Target IP '${COMPANION_HOST}' does NOT exist on any active host interface!${NC}"
    echo -e "    The booted GDC node will fail to connect and crash during early-commands."
    echo ""
    echo -e "${YELLOW}Available local IP addresses on this host:${NC}"
    for ip in "${HOST_IPS[@]}"; do
        # Ignore standard loopback and link-local to keep it clean
        if [[ "${ip}" != "127.0.0.1" && ! "${ip}" =~ ^169\.254 && ! "${ip}" =~ : ]]; then
            echo -e "  - ${BOLD}${ip}${NC}"
        fi
    done
    echo ""
    echo -e "${YELLOW}Action Required:${NC}"
    echo -e "  Update ${BOLD}INSTALL_COMPANION_URL${NC} inside ${BOLD}src/build/build.env${NC} to use one of the active IPs above,"
    echo -e "  then run ${BOLD}./buildAll.sh${NC} to compile and repackage the ISO."
    echo "=============================================================================="
fi

# 3. Check if the companion process is currently running
echo -e "[-] Querying active companion server state..."
COMPANION_PIDS=$(pgrep -f "install_companion.py" || echo "")

if [[ -n "${COMPANION_PIDS}" ]]; then
    echo -e "${GREEN}[x] Active Log Receiver process found (PID: ${COMPANION_PIDS}).${NC}"
else
    echo -e "${YELLOW}[!] Note: No active 'install_companion.py' process was found running locally.${NC}"
    echo -e "    Start the listener in a separate terminal tab using:"
    echo -e "    ${BOLD}./src/build/install_companion.py ${COMPANION_PORT}${NC}"
fi

# 4. Check if the port is actively listening
PORT_LISTENING=false
if command -v ss &>/dev/null; then
    if ss -tulpn 2>/dev/null | grep -q ":${COMPANION_PORT} "; then
        PORT_LISTENING=true
    fi
elif command -v netstat &>/dev/null; then
    if netstat -tulpn 2>/dev/null | grep -q ":${COMPANION_PORT} "; then
        PORT_LISTENING=true
    fi
fi

if [[ "${PORT_LISTENING}" == "true" ]]; then
    echo -e "${GREEN}[x] SUCCESS: Port ${COMPANION_PORT} is actively listening on this host!${NC}"
else
    echo -e "${RED}[!] Error: Nothing is currently listening on Port ${COMPANION_PORT}!${NC}"
    echo -e "    Please start the companion server to listen on this port."
fi

echo "=============================================================================="
if [[ "${IP_MATCHED}" == "true" && "${PORT_LISTENING}" == "true" ]]; then
    echo -e "${GREEN}${BOLD}[SUCCESS] Your host IP and port configurations are fully aligned and reachable!${NC}"
else
    echo -e "${RED}${BOLD}[MISMATCH] Connection setup is misaligned. Please review the warnings above.${NC}"
fi
echo "=============================================================================="
