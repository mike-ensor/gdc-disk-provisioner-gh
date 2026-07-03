import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add src/build directory to python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src/build')))
import scan_ips

class TestGDCIPScanner(unittest.TestCase):

    @patch('time.sleep', return_value=None) # Fast execution by mocking sleep splay
    @patch('subprocess.run')
    @patch('subprocess.getoutput')
    def test_successful_allocation_when_some_ips_taken(self, mock_getoutput, mock_run, mock_sleep):
        # Setup mocks
        # Candidate range: .8 to .15. Assume .8 and .10 are taken, so .9 should be selected.
        
        def mock_subprocess_run(args, **kwargs):
            mock_res = MagicMock()
            target_ip = args[-1]
            if target_ip in ["192.168.9.8", "192.168.9.10"]:
                mock_res.returncode = 0
                mock_res.stdout = f"{target_ip}  00:11:22:33:44:55\n"
            else:
                mock_res.returncode = 1
                mock_res.stdout = ""
            return mock_res

        mock_run.side_effect = mock_subprocess_run
        mock_getoutput.return_value = "" # No neighbors

        # Run scanner on CIDR
        selected_ip = scan_ips.scan_network("192.168.9.8/29", "enp1s0", passes=2)
        
        self.assertEqual(selected_ip, "192.168.9.9")

    @patch('time.sleep', return_value=None)
    @patch('subprocess.run')
    @patch('subprocess.getoutput')
    def test_fallback_when_all_ips_taken(self, mock_getoutput, mock_run, mock_sleep):
        # GIVEN all candidates in 192.168.9.8/29 are taken
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "192.168.9.8  00:11:22:33:44:55\n" # returns responses for any IP queried
        mock_run.return_value = mock_res
        mock_getoutput.return_value = ""

        # Run scanner
        selected_ip = scan_ips.scan_network("192.168.9.8/29", "enp1s0", passes=1)
        
        self.assertIsNone(selected_ip)

    def test_fallback_ip_outside_cidr_range_validation(self):
        # Validate that system exits with status 3 when fallback IP is outside the CIDR scanning range
        with patch('sys.argv', ['scan_ips.py', '--cidr', '192.168.9.8/29', '--fallback', '192.168.9.254', '--interface', 'enp1s0']):
            with self.assertRaises(SystemExit) as cm:
                scan_ips.main()
            self.assertEqual(cm.exception.code, 3)

if __name__ == '__main__':
    unittest.main()
