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

import os
import re
import sys

def log_info(msg):
    print(f"[-] [Netplan-Hydrator] {msg}")

def log_error(msg):
    print(f"[!] [Netplan-Hydrator] ERROR: {msg}", file=sys.stderr)

def remove_empty_sections(yaml_text, section_names=('vlans',)):
    """
    Removes section headers (like 'vlans:') ONLY if they have no children
    (i.e. followed immediately by EOF, another section at equal/less indentation, or comments/blank lines).
    Never removes a section header if it has indented child elements.
    """
    lines = yaml_text.splitlines()
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        matched = False
        for sec in section_names:
            m = re.match(r'^(\s*)' + re.escape(sec) + r':\s*$', line)
            if m:
                matched = True
                indent = len(m.group(1))
                # Check subsequent lines for children
                has_children = False
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    stripped = next_line.strip()
                    if stripped and not stripped.startswith('#'):
                        next_indent = len(next_line) - len(next_line.lstrip())
                        if next_indent > indent:
                            has_children = True
                        break
                    j += 1
                if has_children:
                    result.append(line)
                else:
                    log_info(f"Purging empty/dangling '{sec}:' section from Netplan config.")
                break
        if not matched:
            result.append(line)
        i += 1
    trailing_newline = '\n' if yaml_text.endswith('\n') else ''
    return '\n'.join(result) + trailing_newline

def get_physical_interfaces(sys_class_net='/sys/class/net'):
    try:
        ifaces = os.listdir(sys_class_net)
        # Filter candidate ethernet interfaces: start with 'e' and do not contain '.'
        ethernet_ifaces = [i for i in ifaces if i.startswith('e') and '.' not in i]
        num_ethernet = len(ethernet_ifaces)

        phys = []
        for i in ethernet_ifaces:
            if (i != 'eth0') or (i == 'eth0' and num_ethernet == 1):
                carrier_path = os.path.join(sys_class_net, i, 'carrier')
                try:
                    with open(carrier_path, 'r') as f:
                        if f.read().strip() == '1':
                            phys.append(i)
                except Exception:
                    pass
        
        # If no physically connected interfaces are found, fallback to candidate interfaces
        if not phys:
            phys = [i for i in ethernet_ifaces if (i != 'eth0') or (i == 'eth0' and num_ethernet == 1)]
            
        phys.sort()
        return phys
    except Exception as e:
        log_error(f"Failed to list network interfaces from {sys_class_net}: {e}")
        return []

def load_env_vars(env_path="/tmp/allocated_ips.env"):
    env = {}

    # 1. Sourcing bootstrap defaults from CDROM / workspace if present
    bootstrap_candidates = [
        "/cdrom/custom-data/bootstrap_network.env",
        "/tmp/bootstrap_network.env",
        "custom-data/bootstrap_network.env",
        "build-workspace/custom-iso/custom-data/bootstrap_network.env",
        "../../build-workspace/custom-iso/custom-data/bootstrap_network.env",
    ]
    for b_path in bootstrap_candidates:
        if os.path.exists(b_path):
            log_info(f"Loading bootstrap network defaults from {b_path}")
            try:
                with open(b_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and '=' in line and not line.startswith('#'):
                            k, v = line.split('=', 1)
                            env[k.strip()] = v.strip()
                break
            except Exception as e:
                log_error(f"Failed to read bootstrap network defaults from {b_path}: {e}")

    # 2. Dynamic runtime allocation overrides (from scan_ips if executed)
    if os.path.exists(env_path):
        log_info(f"Sourcing dynamic allocation properties from {env_path}")
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()

    # 3. Final fallbacks if neither dynamic nor bootstrap provided values
    if "MACHINE_IP" not in env:
        if "BOOTSTRAP_MACHINE_IP_CIDR" in env:
            env["MACHINE_IP"] = env["BOOTSTRAP_MACHINE_IP_CIDR"].split('/')[0]
        elif "MACHINE_IP_CIDR" in env:
            env["MACHINE_IP"] = env["MACHINE_IP_CIDR"].split('/')[0]
        else:
            log_info("Dynamic allocation state missing. Defaulting to fallback .14")
            env["MACHINE_IP"] = "192.168.4.14"

    if "K8S_IP" not in env:
        if "BOOTSTRAP_K8S_IP_CIDR" in env:
            env["K8S_IP"] = env["BOOTSTRAP_K8S_IP_CIDR"].split('/')[0]
        elif "K8S_IP_CIDR" in env:
            env["K8S_IP"] = env["K8S_IP_CIDR"].split('/')[0]
        else:
            env["K8S_IP"] = "172.31.250.10"

    return env

def main(template_path=None, target_path=None, sys_class_net='/sys/class/net', env_path='/tmp/allocated_ips.env', target_dir='/target'):
    log_info("Starting GDC Structured Netplan Hydration...")
    
    # 1. Interface Auto-Detection
    ifaces = get_physical_interfaces(sys_class_net)
    num_ifaces = len(ifaces)
    
    if num_ifaces == 0:
        log_info("No physical interfaces starting with 'e' detected. Defaulting to mock host ['eth0'] for validation.")
        ifaces = ["eth0"]
        num_ifaces = 1
        
    log_info(f"Detected {num_ifaces} physical network interface(s): {', '.join(ifaces)}")
    
    # 2. Load Allocation Variables
    env_vars = load_env_vars(env_path)
    
    # Extract CIDR masks dynamically from template context or default
    machine_cidr_raw = env_vars.get("BOOTSTRAP_MACHINE_IP_CIDR", env_vars.get("MACHINE_IP_CIDR", "192.168.4.11/24"))
    machine_mask = machine_cidr_raw.split('/')[1] if '/' in machine_cidr_raw else "24"
    
    k8s_cidr_raw = env_vars.get("BOOTSTRAP_K8S_IP_CIDR", env_vars.get("K8S_IP_CIDR", "172.31.250.10/24"))
    k8s_mask = k8s_cidr_raw.split('/')[1] if '/' in k8s_cidr_raw else "24"
    
    # Construct complete CIDR addresses
    machine_ip_cidr = f"{env_vars.get('MACHINE_IP')}/{machine_mask}"
    k8s_ip_cidr = f"{env_vars.get('K8S_IP')}/{k8s_mask}"
    
    # 3. Define placeholders and assign the first physical NIC as the primary GDC interface
    prod_iface = ifaces[0]
    log_info(f"Primary GDC interface assigned to: {prod_iface}")
    replacements = {
        "__MGMT_IFACE__": prod_iface,
        "__PHYS_IFACE__": prod_iface,
        "__MACHINE_IP_CIDR__": machine_ip_cidr,
        "__K8S_IP_CIDR__": k8s_ip_cidr,
    }
        
    # 4. Load the raw Netplan template as text
    if not template_path:
        template_path = "/cdrom/custom-data/network-template.yaml"
        if not os.path.exists(template_path):
            # Fallback for build/host-side validation testing
            template_path = "build-workspace/custom-iso/custom-data/network-template.yaml"
            if not os.path.exists(template_path):
                template_path = "../../build-workspace/custom-iso/custom-data/network-template.yaml"
            
    if not os.path.exists(template_path):
        log_error(f"Template path {template_path} does not exist!")
        sys.exit(1)
        
    with open(template_path, 'r') as f:
        content = f.read()
            
    # 5. Programmatic purging of the old management interface configuration block
    log_info("Purging management interface configuration block...")
    start_marker = "# __MGMT_IFACE_START__"
    end_marker = "# __MGMT_IFACE_END__"
    if start_marker in content and end_marker in content:
        parts = content.split(start_marker)
        before = parts[0]
        after = parts[1].split(end_marker)[1]
        content = before + after
            
    # 6. Apply text replacements for the primary interface
    for placeholder, replacement in replacements.items():
        content = content.replace(placeholder, replacement)
        
    # 6b. Clean up dangling YAML keys resulting from empty Jinja evaluation
    # If vlans: is left dangling with no children, it crashes netplan generate
    content = remove_empty_sections(content, ('vlans',))
        
    # 7. Dynamically append any secondary and additional NICs as plain DHCP interfaces
    if len(ifaces) > 1:
        extra_configs = []
        for extra_iface in ifaces[1:]:
            log_info(f"Dynamically appending additional NIC: {extra_iface} (Plain DHCP)")
            extra_configs.append(f"    {extra_iface}:")
            extra_configs.append(f"      dhcp4: true")
            extra_configs.append(f"      dhcp6: no")
            extra_configs.append(f"      link-local: []")
            extra_configs.append(f"      optional: true")
            
        ethernets_line = "  ethernets:"
        if ethernets_line in content:
            parts = content.split(ethernets_line, 1)
            content = parts[0] + ethernets_line + "\n" + "\n".join(extra_configs) + "\n" + parts[1]
            
    # 7. Write final Netplan configuration to target
    if not target_path:
        target_path = os.path.join(target_dir, "etc/netplan/01-netcfg.yaml")
        if not os.path.exists(target_dir):
            target_path = "/tmp/01-netcfg.yaml" # fallback for test environments
        
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    with open(target_path, 'w') as f:
        f.write(content)
    os.chmod(target_path, 0o600)
    log_info(f"Hydrated Netplan successfully compiled and written to {target_path}")

if __name__ == "__main__":
    main()
