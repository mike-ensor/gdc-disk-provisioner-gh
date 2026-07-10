import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import ipaddress

# Add bin directory or the script's path so we can import modules if needed,
# or mock the main script behavior. Since we keep it in bin/crash-cart-scan-subnet.sh,
# we will import it directly by loading the source file dynamically.
import importlib.util

import importlib.machinery

def load_scanner_module():
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../bin/crash-cart-scan-subnet.sh'))
    loader = importlib.machinery.SourceFileLoader("crash_cart_scanner", script_path)
    spec = importlib.util.spec_from_loader("crash_cart_scanner", loader)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec from {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["crash_cart_scanner"] = module
    spec.loader.exec_module(module)
    return module

class TestCrashCartScanner(unittest.TestCase):

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_cidr_parsing_and_exclusions(self, mock_socket, mock_run):
        # Load the module dynamically
        scanner = load_scanner_module()
        
        # Test 1: Verify parsing CIDR and extracting exclusions
        cidr = "192.168.9.230/27"
        net = ipaddress.ip_network(cidr, strict=False)
        hosts = [str(ip) for ip in net.hosts()]
        
        # Usable range for /27 should have 30 host addresses (.225 to .254)
        self.assertEqual(len(hosts), 30)
        self.assertEqual(hosts[0], "192.168.9.225")
        self.assertEqual(hosts[-1], "192.168.9.254")

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_target_identification_and_diagnostics(self, mock_socket, mock_run):
        scanner = load_scanner_module()
        
        # Configure mock return values for subprocess/socket to simulate an active unidentified host
        # Let's say 192.168.9.230 is reachable (ping = True) and has SSH open (ssh = True)
        mock_socket_instance = MagicMock()
        mock_socket_instance.connect_ex.return_value = 0 # SSH port is open
        mock_socket.return_value = mock_socket_instance

        # Mock ping subprocess to succeed (returncode=0)
        # Mock SSH diagnostics subprocess to succeed
        def mock_subprocess_run(args, **kwargs):
            res = MagicMock()
            if "ping" in args:
                res.returncode = 0
            elif "sshpass" in args:
                res.returncode = 0
                res.stdout = "test-node-1\nPRETTY_NAME=\"Ubuntu 24.04 LTS\""
            return res
        mock_run.side_effect = mock_subprocess_run

        active = scanner.check_ip_state("192.168.9.230", 1.0)
        self.assertIsNotNone(active)
        self.assertEqual(active["ip"], "192.168.9.230")
        self.assertTrue(active["ping"])
        self.assertTrue(active["ssh"])

if __name__ == '__main__':
    unittest.main()
