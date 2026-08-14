import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import ipaddress
import json
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src/build')))
import scan_ips

class TestGDCIPScanner(unittest.TestCase):

    def test_expand_range(self):
        ips = scan_ips.expand_range("192.168.109.100-192.168.109.102")
        self.assertEqual(ips, ["192.168.109.100", "192.168.109.101", "192.168.109.102"])

    @patch('subprocess.run')
    def test_is_ip_taken_ping_response(self, mock_run):
        def mock_subprocess_run(args, **kwargs):
            mock_res = MagicMock()
            mock_res.returncode = 0
            if args[0] == "ip":
                mock_res.stdout = "1: lo inet 127.0.0.1/8 scope host lo"
            elif args[0] == "ping":
                mock_res.stdout = "64 bytes from 192.168.9.1: icmp_seq=1 ttl=64 time=0.068 ms\nrtt min/avg/max/mdev = 0.068/0.068/0.068/0.000 ms"
            else:
                mock_res.stdout = ""
                mock_res.returncode = 1
            return mock_res
            
        mock_run.side_effect = mock_subprocess_run
        
        with patch('subprocess.getoutput', return_value=""):
            taken = scan_ips.is_ip_taken("192.168.9.1", "eth0")
            self.assertTrue(taken)

    @patch('subprocess.run')
    def test_is_ip_taken_local_interface_bypass(self, mock_run):
        # Test that an IP assigned locally on the interface skips the ping check
        # and relies on ARP which will correctly report False (since it's not taken by *another* host)
        def mock_subprocess_run(args, **kwargs):
            mock_res = MagicMock()
            if args[0] == "ip":
                mock_res.returncode = 0
                mock_res.stdout = "14: eth0    inet 192.168.9.12/24 brd 192.168.9.255 scope global dynamic noprefixroute eth0"
            elif args[0] == "ping":
                self.fail("Ping should not be called for a locally attached IP")
            else:
                mock_res.returncode = 1
                mock_res.stdout = ""
            return mock_res
            
        mock_run.side_effect = mock_subprocess_run
        
        with patch('subprocess.getoutput', return_value=""):
            taken = scan_ips.is_ip_taken("192.168.9.12", "eth0")
            self.assertFalse(taken)

if __name__ == '__main__':
    unittest.main()
