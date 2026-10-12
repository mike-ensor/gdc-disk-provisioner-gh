#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for Bootimus API schema compatibility across versions (0.1.69 list vs 0.1.79+ dict)."""

import io
import json
import os
import sys
import unittest
import urllib.error
from email.message import Message
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "build"))

import bootimus


class TestBootimusApiCompatibility(unittest.TestCase):
    """Tests handling of Bootimus 0.1.69 vs 0.1.79+ API response payloads."""

    def test_extract_images_v0_1_69_list(self):
        """Verifies extract_images handles Bootimus 0.1.69 format (data is a list of image dicts)."""
        raw_res = {
            "success": True,
            "data": [
                {"id": 1, "filename": "sync/image-a.iso", "name": "image-a", "size": 1000},
                {"id": 2, "filename": "sync/image-b.iso", "name": "image-b", "size": 2000},
            ]
        }
        extracted = bootimus.extract_images(raw_res)
        self.assertEqual(len(extracted), 2)
        self.assertEqual(extracted[0]["filename"], "sync/image-a.iso")
        self.assertEqual(extracted[1]["filename"], "sync/image-b.iso")

    def test_extract_images_v0_1_79_single_dict(self):
        """Verifies extract_images handles Bootimus 0.1.79+ format (data is a single image dict)."""
        raw_res = {
            "success": True,
            "data": {
                "id": 498,
                "filename": "sync/gdc-labs-24.04-v0.10.5-debug.iso",
                "name": "gdc-labs-24.04-v0.10.5-debug",
                "size": 6557030400,
                "enabled": False,
                "extracted": False
            }
        }
        extracted = bootimus.extract_images(raw_res)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["filename"], "sync/gdc-labs-24.04-v0.10.5-debug.iso")
        self.assertEqual(extracted[0]["size"], 6557030400)

    def test_extract_images_not_found_or_error(self):
        """Verifies extract_images safely returns an empty list for 404 error responses."""
        res_404 = {"success": False, "error": "Image not found"}
        self.assertEqual(bootimus.extract_images(res_404), [])

        res_none_data = {"success": True, "data": None}
        self.assertEqual(bootimus.extract_images(res_none_data), [])

        res_empty_list = {"success": True, "data": []}
        self.assertEqual(bootimus.extract_images(res_empty_list), [])

        res_empty_dict = {"success": True, "data": {}}
        self.assertEqual(bootimus.extract_images(res_empty_dict), [])

        self.assertEqual(bootimus.extract_images(None), [])
        self.assertEqual(bootimus.extract_images(""), [])

    def test_api_request_allow_404(self):
        """Verifies api_request with allow_404=True returns error JSON on HTTP 404."""
        err_body = b'{"success": false, "error": "Image not found"}'
        fp = io.BytesIO(err_body)
        msg = Message()
        http_err = urllib.error.HTTPError(
            url="http://mock/api/images?filename=sync%2Ftest.iso",
            code=404,
            msg="Not Found",
            hdrs=msg,
            fp=fp
        )

        with mock.patch("urllib.request.urlopen", side_effect=http_err):
            # allow_404=True should parse error body without raising
            res = bootimus.api_request(
                "http://mock/api/images?filename=sync%2Ftest.iso",
                allow_404=True,
                retries=1
            )
            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("error"), "Image not found")

    def test_api_request_disallow_404_raises(self):
        """Verifies api_request default (allow_404=False) continues to raise HTTPError on 404."""
        err_body = b'{"success": false, "error": "Image not found"}'
        fp = io.BytesIO(err_body)
        msg = Message()
        http_err = urllib.error.HTTPError(
            url="http://mock/api/images?filename=sync%2Ftest.iso",
            code=404,
            msg="Not Found",
            hdrs=msg,
            fp=fp
        )

        with mock.patch("urllib.request.urlopen", side_effect=http_err):
            with self.assertRaises(urllib.error.HTTPError):
                bootimus.api_request(
                    "http://mock/api/images?filename=sync%2Ftest.iso",
                    allow_404=False,
                    retries=1
                )

    def test_main_step4_v0_1_79_dictionary_regression(self):
        """Regression test reproducing line 485 with Bootimus 0.1.79 single-dict response."""
        target_iso = "gdc-labs-24.04-v0.10.5-debug.iso"
        full_filename = f"sync/{target_iso}"

        image_dict = {
            "id": 498,
            "filename": full_filename,
            "name": "gdc-labs-24.04-v0.10.5-debug",
            "size": 6557030400,
            "enabled": False,
            "extracted": True,
            "boot_method": "kernel",
            "distro": "ubuntu",
            "boot_params": "boot=casper initrd=initrd ip=dhcp netboot=url url=http://192.168.254.12:16000/isos/sync/gdc-labs-24.04-v0.10.5-debug.iso root=/dev/ram0 ramdisk_size=7500000 autoinstall apparmor=0 console=tty1 console=ttyS0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp ds=nocloud-net;s=http://192.168.254.12:16000/isos/sync/gdc-labs-24.04-v0.10.5-debug/iso/nocloud/"
        }

        # Step 4 queries: images?filename=... returning 0.1.79 single dict
        v0_1_79_response = {
            "success": True,
            "data": image_dict
        }

        def mock_api_call(url, method="GET", data=None, token=None, **kwargs):
            if "/login" in url:
                return {"data": {"token": "mock-token"}}
            if url.endswith("/images"):
                return {"success": True, "data": [image_dict]}
            if "images?filename=" in url:
                if method == "PUT":
                    return {"success": True, "data": image_dict}
                return v0_1_79_response
            return {"success": True}

        with mock.patch.object(bootimus, "get_bootimus_credentials", return_value=("admin", "secret")):
            with mock.patch.object(bootimus, "api_request", side_effect=mock_api_call):
                with mock.patch("time.sleep"):
                    # Calling main with the target ISO
                    test_args = ["bootimus.py", target_iso]
                    with mock.patch.object(sys, "argv", test_args):
                        # Should complete without throwing AttributeError: 'str' object has no attribute 'get'
                        bootimus.main()

    def test_format_mac_address(self):
        """Verifies MAC address normalization across various standard delimiters and casings."""
        self.assertEqual(bootimus.format_mac_address("00:11:22:33:44:55"), "00:11:22:33:44:55")
        self.assertEqual(bootimus.format_mac_address("00-11-22-33-44-55"), "00:11:22:33:44:55")
        self.assertEqual(bootimus.format_mac_address("001122334455"), "00:11:22:33:44:55")
        self.assertEqual(bootimus.format_mac_address("AA:BB:CC:DD:EE:FF"), "aa:bb:cc:dd:ee:ff")
        self.assertEqual(bootimus.format_mac_address(""), "")
        self.assertEqual(bootimus.format_mac_address(None), "")

    def test_set_client_next_boot(self):
        """Verifies set_client_next_boot sends properly structured POST request to Bootimus API."""
        with mock.patch.object(bootimus, "api_request") as mock_req:
            mock_req.return_value = {"success": True, "message": "Next boot set"}
            res = bootimus.set_client_next_boot(
                token="tok-123",
                mac_address="00:11:22:33:44:55",
                image_filename="gdc-labs-24.04-v0.10.19-debug.iso"
            )
            self.assertTrue(res["success"])
            mock_req.assert_called_once_with(
                f"{bootimus.API_BASE}/clients/next-boot",
                method="POST",
                data={
                    "mac_address": "00:11:22:33:44:55",
                    "image_filename": "sync/gdc-labs-24.04-v0.10.19-debug.iso"
                },
                token="tok-123"
            )

    def test_clear_client_next_boot(self):
        """Verifies clear_client_next_boot sends empty image_filename to clear next-boot action."""
        with mock.patch.object(bootimus, "api_request") as mock_req:
            mock_req.return_value = {"success": True, "message": "Next boot action cleared"}
            res = bootimus.clear_client_next_boot(
                token="tok-123",
                mac_address="00-11-22-33-44-55"
            )
            self.assertTrue(res["success"])
            mock_req.assert_called_once_with(
                f"{bootimus.API_BASE}/clients/next-boot",
                method="POST",
                data={
                    "mac_address": "00:11:22:33:44:55",
                    "image_filename": ""
                },
                token="tok-123"
            )

    def test_main_next_boot_cli_mac(self):
        """Verifies main CLI --next-boot --mac dispatches next-boot API call and exits cleanly."""
        with mock.patch.object(bootimus, "get_bootimus_credentials", return_value=("admin", "pass")):
            with mock.patch.object(bootimus, "api_request") as mock_req:
                mock_req.side_effect = [
                    {"data": {"token": "auth-token"}},
                    {"success": True, "message": "Next boot set"}
                ]
                test_args = [
                    "bootimus.py",
                    "--next-boot", "sync/gdc-labs-24.04-v0.10.19-debug.iso",
                    "--mac", "00:11:22:33:44:55"
                ]
                with mock.patch.object(sys, "argv", test_args):
                    with self.assertRaises(SystemExit) as cm:
                        bootimus.main()
                    self.assertEqual(cm.exception.code, 0)
                mock_req.assert_any_call(
                    f"{bootimus.API_BASE}/clients/next-boot",
                    method="POST",
                    data={
                        "mac_address": "00:11:22:33:44:55",
                        "image_filename": "sync/gdc-labs-24.04-v0.10.19-debug.iso"
                    },
                    token="auth-token"
                )

    def test_main_clear_next_boot_cli_all_targets(self):
        """Verifies main CLI --clear-next-boot --all-targets clears next-boot across all clients."""
        mock_clients = {
            "success": True,
            "data": [
                {"mac_address": "00:11:22:33:44:11", "name": "node-1"},
                {"mac_address": "00:11:22:33:44:22", "name": "node-2"},
            ]
        }
        with mock.patch.object(bootimus, "get_bootimus_credentials", return_value=("admin", "pass")):
            with mock.patch.object(bootimus, "api_request") as mock_req:
                mock_req.side_effect = [
                    {"data": {"token": "auth-token"}},
                    mock_clients,
                    {"success": True, "message": "Cleared"},
                    {"success": True, "message": "Cleared"}
                ]
                test_args = ["bootimus.py", "--clear-next-boot", "--all-targets"]
                with mock.patch.object(sys, "argv", test_args):
                    with self.assertRaises(SystemExit) as cm:
                        bootimus.main()
                    self.assertEqual(cm.exception.code, 0)

    def test_parse_target_machines_space_and_csv(self):
        """Verifies parse_target_machines correctly parses both space-separated and CSV IP strings."""
        space_separated = "192.168.9.241 192.168.9.242 192.168.9.243 192.168.9.246"
        csv_separated = "192.168.9.241,192.168.9.242,192.168.9.243,192.168.9.246"
        mixed_separated = "['192.168.9.241', '192.168.9.242', 192.168.9.243, 192.168.9.246]"
        
        expected = ["192.168.9.241", "192.168.9.242", "192.168.9.243", "192.168.9.246"]
        self.assertEqual(bootimus.parse_target_machines(space_separated), expected)
        self.assertEqual(bootimus.parse_target_machines(csv_separated), expected)
        self.assertEqual(bootimus.parse_target_machines(mixed_separated), expected)
        self.assertEqual(bootimus.parse_target_machines(""), [])
        self.assertEqual(bootimus.parse_target_machines(None), [])

    def test_resolve_target_macs(self):
        """Verifies resolve_target_macs normalizes raw MACs and resolves inventory IPs."""
        raw_mac = "00:11:22:33:44:55"
        self.assertEqual(bootimus.resolve_target_macs([raw_mac]), [raw_mac])

        dash_mac = "AA-BB-CC-DD-EE-FF"
        self.assertEqual(bootimus.resolve_target_macs([dash_mac]), ["aa:bb:cc:dd:ee:ff"])

    def test_main_next_boot_cli_with_targets(self):
        """Verifies main CLI --next-boot --targets with space/CSV string sets next-boot for resolved MACs."""
        with mock.patch.object(bootimus, "get_bootimus_credentials", return_value=("admin", "pass")):
            with mock.patch.object(bootimus, "api_request") as mock_req:
                mock_req.side_effect = [
                    {"data": {"token": "auth-token"}},
                    {"success": True, "message": "Next boot set"},
                    {"success": True, "message": "Next boot set"}
                ]
                test_args = [
                    "bootimus.py",
                    "--next-boot", "sync/gdc-labs-24.04-v0.10.19-debug.iso",
                    "--targets", "00:11:22:33:44:11, 00:11:22:33:44:22"
                ]
                with mock.patch.object(sys, "argv", test_args):
                    with self.assertRaises(SystemExit) as cm:
                        bootimus.main()
                    self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
