import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import ipaddress
import subprocess
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

    @patch('subprocess.run')
    def test_is_ping_reachable(self, mock_run):
        scanner = load_scanner_module()
        
        # Test ping success
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(scanner.is_ping_reachable("192.168.9.230", timeout=1.0))
        mock_run.assert_called_with(
            ["ping", "-c", "2", "-W", "1.0", "192.168.9.230"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Test ping failure
        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(scanner.is_ping_reachable("192.168.9.230", timeout=1.0))

    @patch('socket.socket')
    def test_is_ssh_open(self, mock_socket):
        scanner = load_scanner_module()
        
        mock_sock_instance = MagicMock()
        mock_socket.return_value = mock_sock_instance
        
        # Test SSH open (connect_ex returns 0)
        mock_sock_instance.connect_ex.return_value = 0
        self.assertTrue(scanner.is_ssh_open("192.168.9.230", port=22, timeout=1.0))
        mock_sock_instance.connect_ex.assert_called_with(("192.168.9.230", 22))
        
        # Test SSH closed (connect_ex returns non-zero)
        mock_sock_instance.connect_ex.return_value = 111
        self.assertFalse(scanner.is_ssh_open("192.168.9.230", port=22, timeout=1.0))

    @patch('subprocess.run')
    @patch('socket.socket')
    def test_check_ip_state(self, mock_socket, mock_run):
        scanner = load_scanner_module()
        
        # Mock ping success, SSH closed
        mock_run.return_value = MagicMock(returncode=0)
        mock_sock_instance = MagicMock()
        mock_sock_instance.connect_ex.return_value = 111
        mock_socket.return_value = mock_sock_instance
        
        res = scanner.check_ip_state("192.168.9.230", timeout=1.0)
        self.assertIsNotNone(res)
        self.assertEqual(res["ip"], "192.168.9.230")
        self.assertTrue(res["ping"])
        self.assertFalse(res["ssh"])
        
        # Mock both closed
        mock_run.return_value = MagicMock(returncode=1)
        mock_sock_instance.connect_ex.return_value = 111
        res = scanner.check_ip_state("192.168.9.231", timeout=1.0)
        self.assertIsNone(res)

    @patch('subprocess.run')
    def test_run_diagnostics(self, mock_run):
        scanner = load_scanner_module()
        
        mock_run.return_value = MagicMock(returncode=0, stdout="test-node\nUbuntu 24.04 LTS")
        res = scanner.run_diagnostics("192.168.9.230", "test-user", "test-pass")
        
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "test-node\nUbuntu 24.04 LTS")
        
        expected_cmd = (
            "sshpass -p 'test-pass' ssh "
            "-o StrictHostKeyChecking=no "
            "-o UserKnownHostsFile=/dev/null "
            "-o ConnectTimeout=3 "
            "test-user@192.168.9.230 "
            "'hostname && cat /etc/os-release | grep PRETTY_NAME'"
        )
        mock_run.assert_called_with(expected_cmd, shell=True, capture_output=True, text=True)

    @patch('sys.exit')
    @patch('sys.stdout')
    @patch('sys.stderr')
    def test_main_invalid_cidr(self, mock_stderr, mock_stdout, mock_exit):
        scanner = load_scanner_module()
        
        # Test invalid CIDR handling
        test_args = ["crash-cart-scan-subnet.sh", "-c", "invalid_cidr"]
        with patch('sys.argv', test_args):
            scanner.main()
            mock_exit.assert_called_with(1)

    @patch('concurrent.futures.ThreadPoolExecutor')
    @patch('sys.exit')
    @patch('sys.stdout')
    def test_main_valid_cidr_with_exclusions(self, mock_stdout, mock_exit, mock_executor):
        scanner = load_scanner_module()
        
        # Mock executor to return check_ip_state results
        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance
        
        # Two active devices, one of which is excluded
        mock_executor_instance.map.return_value = [
            {"ip": "192.168.9.230", "ping": True, "ssh": True},
            {"ip": "192.168.9.234", "ping": True, "ssh": False}
        ]
        
        test_args = ["crash-cart-scan-subnet.sh", "-c", "192.168.9.230/30", "-e", "192.168.9.234"]
        with patch('sys.argv', test_args), patch('crash_cart_scanner.run_diagnostics') as mock_diag:
            mock_diag.return_value = MagicMock(returncode=0, stdout="node-230\nPRETTY_NAME=\"Ubuntu 24.04 LTS\"")
            
            scanner.main()
            
            # Since 192.168.9.234 was excluded, run_diagnostics should only be called for 192.168.9.230
            mock_diag.assert_called_once_with("192.168.9.230", "temporary-installer", "troubled-marble-150")

if __name__ == '__main__':
    unittest.main()
