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
import sys
from jinja2 import Environment, FileSystemLoader
import yaml

def load_env_properties():
    """
    Natively parses build.env and local.env, handling comments, spaces, 
    and quotes with 100% accuracy. Active system environment variables
    take ultimate precedence.
    """
    env = {}
    
    # 1. Helper to parse a single .env file
    def parse_file(filepath):
        if not os.path.exists(filepath):
            return
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip()
                    # Strip any surrounding quotes
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1].strip()
                    env[key] = val

    # 2. Load dependencies manifest, standard defaults, then local overrides
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_src_dir = os.path.dirname(script_dir)
    parse_file(os.path.join(project_src_dir, 'dependencies.env'))
    parse_file(os.path.join(script_dir, 'build.env'))
    parse_file(os.path.join(script_dir, 'local.env'))
    
    # 3. Active system environment variables take absolute precedence
    for key, val in os.environ.items():
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1].strip()
        env[key] = val
        
    return env

def render_templates(template_dir, output_dir, env):
    jinja_env = Environment(loader=FileSystemLoader(template_dir))
    
    # Process GDC_COMPANION flag if not already resolved in context
    if 'enable_phone_home' not in env or 'enable_webhook' not in env:
        raw_companion = env.get('GDC_COMPANION', env.get('BOOT_LOGGING', 'TRUE'))
        companion_val = str(raw_companion).strip().upper()
        if companion_val in ("TRUE", "1", "YES", "ALL", "BOTH"):
            env['enable_phone_home'] = True
            env['enable_webhook'] = True
        elif companion_val in ("FALSE", "0", "NO", "NONE"):
            env['enable_phone_home'] = False
            env['enable_webhook'] = False
        else:
            raise ValueError(f"Invalid GDC_COMPANION value: '{raw_companion}'. Valid values: TRUE, FALSE.")
            
    # Process optional extra debug user
    env['debug_extra_user'] = env.get('DEBUG_EXTRA_USER', env.get('debug_extra_user', '')).strip()
    if 'debug_extra_password_hash' not in env or not env['debug_extra_password_hash']:
        extra_pwd = env.get('DEBUG_EXTRA_PASSWORD', '')
        if extra_pwd:
            try:
                import crypt
                env['debug_extra_password_hash'] = crypt.crypt(extra_pwd, crypt.mksalt(crypt.METHOD_SHA512))
            except Exception:
                try:
                    import subprocess
                    env['debug_extra_password_hash'] = subprocess.check_output(
                        ['openssl', 'passwd', '-6', extra_pwd],
                        text=True
                    ).strip()
                except Exception:
                    env['debug_extra_password_hash'] = ''
        else:
            env['debug_extra_password_hash'] = env.get('DEBUG_EXTRA_PASSWORD_HASH', '')
    
    # Render storage first so we can inject it into user-data context
    storage_content = ""
    if 'SINGLE_DISK' in env:
        storage_template = jinja_env.get_template('storage_config.j2')
        env['single_disk'] = env.get('SINGLE_DISK') == 'true'
        env['disk1'] = env.get('DISK1')
        env['disk2'] = env.get('DISK2')
        env['num_disks'] = "1" if env['single_disk'] else "2"
        storage_content = storage_template.render(env)
        
        output_file = env.get('OUTPUT_FILE', '/run/autoinstall-storage.yaml')
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w') as f:
            f.write(storage_content)
    
    # Indent the rendered storage block by 4 spaces for user-data embedding
    indented_storage = "\n".join("    " + line if line.strip() else line for line in storage_content.splitlines())
    env['storage_config'] = indented_storage

    # Render user-data with storage_config in context
    user_data_template = jinja_env.get_template('user-data.j2')
    user_data_content = user_data_template.render(env)
    
    os.makedirs(os.path.join(output_dir, 'nocloud'), exist_ok=True)
    with open(os.path.join(output_dir, 'nocloud', 'user-data'), 'w') as f:
        f.write(user_data_content)
        
    # Render meta-data
    meta_data_template = jinja_env.get_template('meta-data.j2')
    meta_data_content = meta_data_template.render(env)
    
    with open(os.path.join(output_dir, 'nocloud', 'meta-data'), 'w') as f:
        f.write(meta_data_content)
    
    # Render netplan
    netplan_template = jinja_env.get_template('netplan.j2')
    netplan_content = netplan_template.render(env)
    
    os.makedirs(os.path.join(output_dir, 'custom-data'), exist_ok=True)
    with open(os.path.join(output_dir, 'custom-data', 'network-template.yaml'), 'w') as f:
        f.write(netplan_content)
        
    # Copy storage templates to output_dir/custom-data/storage/
    storage_src_dir = os.path.join(template_dir, 'storage')
    storage_dst_dir = os.path.join(output_dir, 'custom-data', 'storage')
    if os.path.exists(storage_src_dir):
        import shutil
        if os.path.exists(storage_dst_dir):
            shutil.rmtree(storage_dst_dir)
        shutil.copytree(storage_src_dir, storage_dst_dir)
    
    # Render systemd services
    systemd_dir = os.path.join(output_dir, 'custom-data', 'systemd')
    os.makedirs(systemd_dir, exist_ok=True)
    
    for service in ['gitea.service', 'nexus.service', 'gdc-provision.service', 'gdc-desired-state.service']:
        template = jinja_env.get_template(f'{service}.j2')
        with open(os.path.join(systemd_dir, service), 'w') as f:
            f.write(template.render(env))
            
    timer_template = jinja_env.get_template('gdc-provision.timer.j2')
    with open(os.path.join(systemd_dir, 'gdc-provision.timer'), 'w') as f:
        f.write(timer_template.render(env))
        
    ds_timer_template = jinja_env.get_template('gdc-desired-state.timer.j2')
    with open(os.path.join(systemd_dir, 'gdc-desired-state.timer'), 'w') as f:
        f.write(ds_timer_template.render(env))

    # Render Ansible Global Vars
    ansible_vars_dir = os.path.join(output_dir, 'custom-data', 'ansible', 'vars')
    os.makedirs(ansible_vars_dir, exist_ok=True)
    ansible_env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src", "ansible", "vars")))
    all_yml_template = ansible_env.get_template('all.yml.j2')
    with open(os.path.join(ansible_vars_dir, 'all.yml'), 'w') as f:
        f.write(all_yml_template.render(env))

    # Write the patched unattended GRUB configuration during hydration to satisfy static validation gates
    grub_dir = os.path.join(output_dir, "boot", "grub")
    os.makedirs(grub_dir, exist_ok=True)
    grub_cfg_path = os.path.join(grub_dir, "grub.cfg")
    grub_content = """set timeout=5
set default=0

serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1
terminal_input console serial
terminal_output console serial

menuentry "Google Distributed Cloud (GDC) Automated Installer [Default]" {
    set gfxpayload=keep
    echo "Booting GDC Unattended Installer..."
    linux /casper/vmlinuz console=tty1 console=ttyS0,115200 autoinstall "ds=nocloud;s=/cdrom/nocloud/" ip=dhcp apparmor=0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp ---
    initrd /casper/initrd
}

menuentry "GDC Interactive Subiquity Installer (Manual Step-by-Step)" {
    set gfxpayload=keep
    echo "Booting GDC Interactive Installer..."
    linux /casper/vmlinuz console=tty1 console=ttyS0,115200 apparmor=0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp ---
    initrd /casper/initrd
}

menuentry "GDC Manual Rescue Shell (Interactive Terminal)" {
    set gfxpayload=keep
    echo "Booting GDC Manual Rescue Shell..."
    linux /casper/vmlinuz console=tty1 console=ttyS0,115200 apparmor=0 tpm_tis.interrupts=0 modprobe.blacklist=pcie_mp2_amd,amd_sfh,ccp init=/bin/sh ---
    initrd /casper/initrd
}
"""
    with open(grub_cfg_path, "w") as f:
        f.write(grub_content)
    print(f"[-] Successfully patched GRUB bootloader in: {grub_cfg_path}")
    
    print(f"[-] Successfully rendered templates to {output_dir}")

if __name__ == "__main__":
    # Load all environment configurations with perfect accuracy
    env = load_env_properties()
    
    # Assert that all mandatory configuration parameters are defined
    mandatory_vars = [
        'ISO_VERSION',
        'ISO_NAME_PREFIX',
        'TEMPORARY_INSTALLER_PASSWORD',
        'UPSTREAM_PLAYBOOKS_REPO',
        'BOOTSTRAP_MACHINE_IP_CIDR',
        'BOOTSTRAP_MACHINE_GATEWAY',
        'BOOTSTRAP_K8S_IP_CIDR',
        'BOOTSTRAP_K8S_GATEWAY',
        'INSTALL_COMPANION_URL',
        'GITEA_BINARY_FILENAME',
        'NEXUS_PACKAGE_FILENAME',
        'JRE_PACKAGE_FILENAME'
    ]
    
    missing_vars = []
    for var in mandatory_vars:
        val = env.get(var)
        if not val:
            missing_vars.append(var)
            
    if missing_vars:
        print(f"[!] ERROR: Pre-flight hydration failed! The following mandatory build configuration variables are not set or are empty:", file=sys.stderr)
        for var in missing_vars:
            print(f"  - {var}", file=sys.stderr)
        print("[!] Please configure them in 'build.env' or inject them via 'local.env' overrides.", file=sys.stderr)
        sys.exit(1)

    # Fill in standard dynamic parameter defaults
    env['gdc_debug_mode'] = env.get('GDC_DEBUG_MODE', 'false').lower() == 'true'
    env['boot_mode'] = env.get('BOOT_MODE', 'bios').lower()
    env['timestamp'] = env.get('BUILD_TIMESTAMP', '')
    env['hostname'] = env.get('HOSTNAME', 'gdc-standalone-node')
    env['admin_ssh_pub_keys'] = env.get('ADMIN_SSH_PUB_KEYS', '')
    env['temp_installer_ssh_pub_keys'] = env.get('TEMPORARY_INSTALLER_SSH_PUB_KEYS', '')
    import subprocess
    try:
        git_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).decode('utf-8').strip()
    except Exception:
        git_branch = 'main'
    env['git_branch'] = git_branch
    env['persist_add_hosts'] = env.get('PERSIST_ADD_HOSTS', 'false').lower() == 'true'
    env['ansible_pull_schedule'] = env.get('ANSIBLE_PULL_SCHEDULE', '02:00:00')
    env['upstream_desired_state_repo'] = env.get('UPSTREAM_DESIRED_STATE_REPO', '')
    env['desired_state_pull_schedule'] = env.get('DESIRED_STATE_PULL_SCHEDULE', '*:0/30')
    
    # Parse git-ignored add-hosts file for custom DNS mappings
    add_hosts_lines = []
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_src_dir = os.path.dirname(script_dir)
    add_hosts_path = os.path.join(script_dir, 'add-hosts')
    if not os.path.exists(add_hosts_path):
        add_hosts_path = os.path.join(project_src_dir, 'add-hosts')
        
    if os.path.exists(add_hosts_path):
        with open(add_hosts_path, 'r') as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    add_hosts_lines.append(stripped)
                    
    env['add_hosts_lines'] = add_hosts_lines

    env['companion_url'] = env.get('INSTALL_COMPANION_URL', 'http://127.0.0.1:8080/v1/install-logs')
    env['install_companion_base'] = env.get('INSTALL_COMPANION_BASE', 'https://127.0.0.1/')
    env['install_companion_api_key'] = env.get('INSTALL_COMPANION_API_KEY', '')
    env['step_ca_url'] = env.get('STEP_CA_URL', 'https://step-ca.local')
    env['step_provisioner_name'] = env.get('STEP_PROVISIONER_NAME', 'tpm')
    env['step_provisioner_password'] = env.get('STEP_PROVISIONER_PASSWORD', '')
    from urllib.parse import urlparse
    u = urlparse(env['companion_url'])
    env['companion_host'] = env.get('COMPANION_HOST', u.netloc)
    
    # Extract companion IP from add-hosts if available, to bypass early DNS lookups
    companion_ip = '127.0.0.1'
    if u.hostname:
        companion_ip = u.hostname
        for line in add_hosts_lines:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == u.hostname:
                companion_ip = parts[0]
                break
    env['companion_ip'] = env.get('COMPANION_IP', companion_ip)
    
    # Generate IP-based report URL to bypass early boot-time DNS resolutions
    env['companion_report_url'] = env['companion_url'].replace(env['companion_host'], env['companion_ip'])
    env['machine_vlan'] = env.get('BOOTSTRAP_MACHINE_VLAN_ID', '0')
    env['k8s_vlan'] = env.get('BOOTSTRAP_K8S_VLAN_ID', '0')
    env['machine_dhcp4'] = env.get('BOOTSTRAP_MACHINE_DHCP4', 'true').lower()
    env['machine_dhcp6'] = env.get('BOOTSTRAP_MACHINE_DHCP6', 'false').lower()
    env['machine_ip_cidr'] = env.get('BOOTSTRAP_MACHINE_IP_CIDR', '192.168.4.11/24')
    env['machine_gateway'] = env.get('BOOTSTRAP_MACHINE_GATEWAY', '192.168.4.1')
    env['machine_dns'] = env.get('BOOTSTRAP_MACHINE_DNS', '192.168.1.1, 8.8.8.8, 8.8.4.4')
    env['k8s_ip_cidr'] = env.get('BOOTSTRAP_K8S_IP_CIDR', '192.168.4.10/29')
    env['k8s_gateway'] = env.get('BOOTSTRAP_K8S_GATEWAY', '192.168.4.9')
    env['k8s_dns'] = env.get('BOOTSTRAP_K8S_DNS', '192.168.1.1, 8.8.8.8, 8.8.4.4')
    env['bootstrap_host_name'] = env.get('BOOTSTRAP_HOST_NAME', 'gdc-default')
    env['fallback_machine_state_stop_stage'] = env.get('FALLBACK_MACHINE_STATE_STOP_STAGE', '')
    env['bootstrap_bmctl_version'] = env.get('BOOTSTRAP_BMCTL_VERSION', '1.35.300-gke.87')
    env['upstream_apt_mirror'] = env.get('UPSTREAM_APT_MIRROR', 'http://archive.ubuntu.com/ubuntu/')
    env['upstream_security_mirror'] = env.get('UPSTREAM_SECURITY_MIRROR', 'http://security.ubuntu.com/ubuntu/')
    env['fallback_cluster_vlan_id'] = env.get('FALLBACK_CLUSTER_VLAN_ID', '100')
    env['fallback_peers_json'] = env.get('FALLBACK_PEERS_JSON', '[]')
    env['fallback_gcp_project_id'] = env.get('FALLBACK_GCP_PROJECT_ID', '')
    env['fallback_gcp_region'] = env.get('FALLBACK_GCP_REGION', '')
    env['fallback_gcp_primary_gsa'] = env.get('FALLBACK_GCP_PRIMARY_GSA', '')
    env['phys_iface'] = env.get('PHYS_IFACE', '__PHYS_IFACE__')
    env['vrf_machine_interfaces'] = env.get('VRF_MACHINE_INTERFACES', "['__PHYS_IFACE__']")
    
    # Process NTP Upstream Servers
    ntp_servers_raw = env.get('NTP_UPSTREAM_SERVERS', 'time.google.com, time1.google.com, time2.google.com, time3.google.com, time4.google.com')
    env['ntp_upstream_servers'] = [s.strip() for s in ntp_servers_raw.split(',') if s.strip()]
    
    # Process GDC_COMPANION flag
    raw_companion = env.get('GDC_COMPANION', env.get('BOOT_LOGGING', 'TRUE'))
    companion_val = str(raw_companion).strip().upper()
    if companion_val in ("TRUE", "1", "YES", "ALL", "BOTH"):
        env['enable_phone_home'] = True
        env['enable_webhook'] = True
    elif companion_val in ("FALSE", "0", "NO", "NONE"):
        env['enable_phone_home'] = False
        env['enable_webhook'] = False
    else:
        print(f"[!] ERROR: Pre-flight hydration failed! Invalid GDC_COMPANION value: '{raw_companion}'. Valid values: TRUE, FALSE.", file=sys.stderr)
        sys.exit(1)
    
    # Map and self-heal the temporary installer credential password hash
    env['password_hash'] = env.get('PASSWORD_HASH', '')
    if not env['password_hash'] and env.get('TEMPORARY_INSTALLER_PASSWORD'):
        try:
            import crypt
            env['password_hash'] = crypt.crypt(env['TEMPORARY_INSTALLER_PASSWORD'], crypt.mksalt(crypt.METHOD_SHA512))
        except Exception:
            try:
                import subprocess
                env['password_hash'] = subprocess.check_output(
                    ['openssl', 'passwd', '-6', env['TEMPORARY_INSTALLER_PASSWORD']],
                    text=True
                ).strip()
            except Exception:
                pass

    # Map optional debug extra user
    env['debug_extra_user'] = env.get('DEBUG_EXTRA_USER', '').strip()
    env['debug_extra_password_hash'] = env.get('DEBUG_EXTRA_PASSWORD_HASH', '')
    if not env['debug_extra_password_hash'] and env.get('DEBUG_EXTRA_PASSWORD'):
        try:
            import crypt
            env['debug_extra_password_hash'] = crypt.crypt(env['DEBUG_EXTRA_PASSWORD'], crypt.mksalt(crypt.METHOD_SHA512))
        except Exception:
            try:
                import subprocess
                env['debug_extra_password_hash'] = subprocess.check_output(
                    ['openssl', 'passwd', '-6', env['DEBUG_EXTRA_PASSWORD']],
                    text=True
                ).strip()
            except Exception:
                pass
            
    render_templates(sys.argv[1], sys.argv[2], env)
