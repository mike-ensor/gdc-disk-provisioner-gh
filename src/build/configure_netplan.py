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
    
    # Extract CIDR masks from template context or default
    machine_mask = "24"
    k8s_mask = "29"
    
    # Construct complete CIDR addresses
    machine_ip_cidr = f"{env_vars.get('MACHINE_IP')}/{machine_mask}"
    k8s_ip_cidr = f"{env_vars.get('K8S_IP')}/{k8s_mask}"
    
    # 3. Define placeholders
    replacements = {
        "__MACHINE_IP_CIDR__": machine_ip_cidr,
        "__K8S_IP_CIDR__": k8s_ip_cidr,
    }
    
    if num_ifaces > 1:
        mgmt_iface = ifaces[0]
        prod_iface = ifaces[1]
        log_info(f"Dual-NIC environment detected. MGMT: {mgmt_iface} | PROD: {prod_iface}")
        replacements["__MGMT_IFACE__"] = mgmt_iface
        replacements["__PHYS_IFACE__"] = prod_iface
    else:
        prod_iface = ifaces[0]
        log_info(f"Single-NIC environment detected. PROD: {prod_iface}")
        replacements["__PHYS_IFACE__"] = prod_iface
        
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
            
    # 5. Programmatic purging of MGMT section if single-NIC
    if num_ifaces == 1:
        log_info("Purging management interface configuration block from Single-NIC layout...")
        start_marker = "# __MGMT_IFACE_START__"
        end_marker = "# __MGMT_IFACE_END__"
        if start_marker in content and end_marker in content:
            parts = content.split(start_marker)
            before = parts[0]
            after = parts[1].split(end_marker)[1]
            content = before + after
            
    # 6. Apply text replacements
    for placeholder, replacement in replacements.items():
        content = content.replace(placeholder, replacement)
        
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
    
    # 8. Pre-reboot Netplan validation via chroot generate
    netplan_bin_path = os.path.join(target_dir, "usr/sbin/netplan")
    netplan_bin_path_alt = os.path.join(target_dir, "usr/bin/netplan")
    if os.path.exists(netplan_bin_path) or os.path.exists(netplan_bin_path_alt):
        log_info("Running pre-reboot Netplan schema Dry-Run validation inside target chroot...")
        try:
            # Move cloud-init temporary configs aside to let Netplan focus exclusively on the new config
            ci_netplan = os.path.join(target_dir, "etc/netplan/50-cloud-init.yaml")
            if os.path.exists(ci_netplan):
                os.rename(ci_netplan, ci_netplan + ".bak")
                
            subprocess.run(["chroot", target_dir, "netplan", "generate"], check=True, capture_output=True, text=True)
            log_info("[GDC-VALIDATE-SUCCESS] Netplan dry-run validation passed cleanly.")
        except subprocess.CalledProcessError as e:
            log_error(f"Netplan Dry-Run generate failed inside target filesystem!\nStdout: {e.stdout}\nStderr: {e.stderr}")
            sys.exit(1)
        except Exception as e:
            log_error(f"Validation framework failed: {e}")
            sys.exit(1)
    else:
        log_info("No netplan binary found in target chroot. Skipping dry-run validation (OK for mock tests).")

if __name__ == "__main__":
    main()
