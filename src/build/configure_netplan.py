#!/usr/bin/env python3
import os
import sys
import subprocess

def log_info(msg):
    print(f"[-] [Netplan-Hydrator] {msg}")

def log_error(msg):
    print(f"[!] [Netplan-Hydrator] ERROR: {msg}", file=sys.stderr)

def get_physical_interfaces(sys_class_net='/sys/class/net'):
    try:
        ifaces = os.listdir(sys_class_net)
        # Filter: starts with 'e', does not contain '.', is not virtual/loopback
        phys = [i for i in ifaces if i.startswith('e') and '.' not in i and i != 'eth0' or (i == 'eth0' and len(ifaces) == 1)]
        phys.sort()
        return phys
    except Exception as e:
        log_error(f"Failed to list network interfaces from {sys_class_net}: {e}")
        return []

def load_env_vars(env_path="/tmp/allocated_ips.env"):
    env = {}
    if os.path.exists(env_path):
        log_info(f"Sourcing dynamic allocation properties from {env_path}")
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    else:
        log_info("Dynamic allocation state missing. Defaulting to fallback .14")
        env["MACHINE_IP"] = "192.168.9.14"
        env["K8S_IP"] = "192.168.109.14"
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
    machine_cidr_raw = env_vars.get("MACHINE_IP_CIDR", "192.168.9.11/24")
    machine_mask = machine_cidr_raw.split('/')[1] if '/' in machine_cidr_raw else "24"
    
    k8s_cidr_raw = env_vars.get("K8S_IP_CIDR", "192.168.109.10/29")
    k8s_mask = k8s_cidr_raw.split('/')[1] if '/' in k8s_cidr_raw else "29"
    
    # Construct complete CIDR addresses
    machine_ip_cidr = f"{env_vars.get('MACHINE_IP')}/{machine_mask}"
    k8s_ip_cidr = f"{env_vars.get('K8S_IP')}/{k8s_mask}"
    
    # 3. Define placeholders and assign the first physical NIC as the primary GDC interface
    prod_iface = ifaces[0]
    log_info(f"Primary GDC interface assigned to: {prod_iface}")
    replacements = {
        "__MGMT_IFACE__": prod_iface,
        "__PHYS_IFACE__": prod_iface,
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
        
    # 7. Dynamically append any secondary and additional NICs as plain DHCP interfaces
    if len(ifaces) > 1:
        extra_configs = []
        for extra_iface in ifaces[1:]:
            log_info(f"Dynamically appending additional NIC: {extra_iface} (Plain DHCP)")
            extra_configs.append(f"    {extra_iface}:")
            extra_configs.append(f"      dhcp4: true")
            extra_configs.append(f"      dhcp6: no")
            extra_configs.append(f"      link-local: []")
            
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
