import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import ipaddress

# Add src/build directory to python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src/build')))
import scan_ips

class TestGDCHybridIPScanner(unittest.TestCase):

    @patch('time.sleep', return_value=None)
    def test_mac_and_dhcp_hashing_subnet_fitting(self, mock_sleep):
        # We test dozens of simulated MAC addresses and DHCP suffixes against 3 different subnets
        subnets = [
            ("192.168.10.1/29", ["192.168.10.1", "192.168.10.2", "192.168.10.3", "192.168.10.4", "192.168.10.5", "192.168.10.6"]),
            ("172.16.1.8/29", ["172.16.1.9", "172.16.1.10", "172.16.1.11", "172.16.1.12", "172.16.1.13", "172.16.1.14"]),
            ("10.200.0.16/29", ["10.200.0.17", "10.200.0.18", "10.200.0.19", "10.200.0.20", "10.200.0.21", "10.200.0.22"])
        ]

        # Generate 24 simulated MAC addresses and 24 non-sequential DHCP suffixes
        simulated_macs = [f"00:00:01:04:02:{hex(i)[2:].zfill(2)}" for i in range(24)]
        simulated_dhcp_suffixes = [230 + (i * 3) % 24 for i in range(24)] # non-sequential suffixes

        for cidr, expected_hosts in subnets:
            net = ipaddress.ip_network(cidr, strict=False)
            hosts = [str(ip) for ip in net.hosts()]
            
            # Assert hosts are exactly what is expected
            self.assertEqual(hosts, expected_hosts)

            for idx_sim, mac in enumerate(simulated_macs):
                dhcp_suffix = simulated_dhcp_suffixes[idx_sim]
                
                # Suffix index calculation
                last_byte = int(mac.split(":")[-1], 16)
                expected_idx = (last_byte + dhcp_suffix) % len(hosts)
                expected_ip = hosts[expected_idx]

                # Run scanner's calculation directly
                preferred_ip = scan_ips.calculate_preferred_ip(mac, dhcp_suffix, hosts)
                
                # Check that computed IP matches expected determinism
                self.assertEqual(preferred_ip, expected_ip)
                # Verify that it fits strictly inside the usable hosts range
                self.assertIn(preferred_ip, hosts)

    @patch('time.sleep', return_value=None)
    @patch('subprocess.run')
    def test_defensive_l2_binding_on_first_claim(self, mock_run, mock_sleep):
        # GIVEN preferred IP is free, it should immediately bind and claim it
        
        # 1. Mock get_mac_address to return ...:d9 (217) and get_dhcp_ip_suffix to return 241
        # Usable hosts of 192.168.9.8/29: [.9, .10, .11, .12, .13, .14]
        # (217 + 241) = 458 % 6 = 2 -> Index 2 (192.168.9.11)
        with patch('scan_ips.get_mac_address', return_value="00:00:01:04:02:d9"):
            with patch('scan_ips.get_dhcp_ip_suffix', return_value=241):
                # Mock subprocess checks
                def mock_subprocess_run(args, **kwargs):
                    mock_res = MagicMock()
                    mock_res.returncode = 1 # Not taken
                    mock_res.stdout = ""
                    # Mock the ip addr add execution
                    if "addr" in args and "add" in args:
                        mock_res.returncode = 0
                    return mock_res

                mock_run.side_effect = mock_subprocess_run
                
                selected_ip = scan_ips.scan_network_hybrid("192.168.9.8/29", "enp1s0")
                
                # Assert correct deterministic IP was claimed
                self.assertEqual(selected_ip, "192.168.9.11")
                
                # Assert that the defensive binding command 'ip addr add 192.168.9.11/24' was called
                binding_call_found = False
                for call in mock_run.call_args_list:
                    call_args = call[0][0]
                    if "ip" in call_args and "addr" in call_args and "add" in call_args and "192.168.9.11/24" in call_args:
                        binding_call_found = True
                        break
                self.assertTrue(binding_call_found)

    @patch('time.sleep', return_value=None)
    @patch('subprocess.run')
    def test_shuffled_fallback_loop_when_preferred_is_taken(self, mock_run, mock_sleep):
        # GIVEN preferred IP is taken, but there is a free fallback candidate
        
        # MAC suffix: 0xd9 (217) and DHCP suffix 241 -> Preferred IP is 192.168.9.11
        with patch('scan_ips.get_mac_address', return_value="00:00:01:04:02:d9"):
            with patch('scan_ips.get_dhcp_ip_suffix', return_value=241):
                # Mock subprocess checks
                def mock_subprocess_run(args, **kwargs):
                    mock_res = MagicMock()
                    target_ip = args[-1]
                    # Assume .11 is TAKEN, but others are free
                    if target_ip == "192.168.9.11":
                        mock_res.returncode = 0
                        mock_res.stdout = "192.168.9.11  00:11:22:33:44:55\n"
                    else:
                        mock_res.returncode = 1
                        mock_res.stdout = ""
                    
                    # Mock the ip addr add execution
                    if "addr" in args and "add" in args:
                        mock_res.returncode = 0
                    return mock_res

                mock_run.side_effect = mock_subprocess_run
                
                selected_ip = scan_ips.scan_network_hybrid("192.168.9.8/29", "enp1s0")
                
                # Assert that preferred IP .11 was NOT selected, but we successfully got a valid fallback IP
                self.assertNotEqual(selected_ip, "192.168.9.11")
                self.assertIn(selected_ip, ["192.168.9.9", "192.168.9.10", "192.168.9.12", "192.168.9.13", "192.168.9.14"])

if __name__ == '__main__':
    unittest.main()
