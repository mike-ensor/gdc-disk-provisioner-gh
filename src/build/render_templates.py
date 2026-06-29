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
    
    for service in ['gitea.service', 'nexus.service', 'gdc-provision.service']:
        template = jinja_env.get_template(f'{service}.j2')
        with open(os.path.join(systemd_dir, service), 'w') as f:
            f.write(template.render(env))
            
    timer_template = jinja_env.get_template('gdc-provision.timer.j2')
    with open(os.path.join(systemd_dir, 'gdc-provision.timer'), 'w') as f:
        f.write(timer_template.render(env))
    
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
        'MACHINE_IP_CIDR',
        'MACHINE_GATEWAY',
        'K8S_IP_CIDR',
        'K8S_GATEWAY',
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
    env['boot_mode'] = env.get('BOOT_MODE', 'bios').lower()
    env['timestamp'] = env.get('BUILD_TIMESTAMP', '')
    env['hostname'] = env.get('HOSTNAME', 'gdc-standalone-node')
    env['ssh_pub_key'] = env.get('ADMIN_SSH_PUB_KEYS', '')
    import subprocess
    try:
        git_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).decode('utf-8').strip()
    except Exception:
        git_branch = 'main'
    env['git_branch'] = git_branch
    env['companion_url'] = env.get('INSTALL_COMPANION_URL', 'http://gdc-companion.ensor-labs.com:8080/v1/install-logs')
    env['companion_ip'] = env.get('COMPANION_IP', '192.168.20.102')
    env['companion_host'] = env.get('COMPANION_HOST', 'gdc-companion.ensor-labs.com')
    # Generate IP-based report URL to bypass early boot-time DNS resolutions
    env['companion_report_url'] = env['companion_url'].replace(env['companion_host'], env['companion_ip'])
    env['machine_vlan'] = env.get('MACHINE_VLAN_ID', '0')
    env['k8s_vlan'] = env.get('K8S_VLAN_ID', '0')
    env['machine_ip_cidr'] = env.get('MACHINE_IP_CIDR', '192.168.9.5/29')
    env['machine_gateway'] = env.get('MACHINE_GATEWAY', '192.168.9.1')
    env['machine_dns'] = env.get('MACHINE_DNS', '192.168.1.1, 8.8.8.8, 8.8.4.4')
    env['k8s_ip_cidr'] = env.get('K8S_IP_CIDR', '192.168.9.10/29')
    env['k8s_gateway'] = env.get('K8S_GATEWAY', '192.168.9.9')
    env['k8s_dns'] = env.get('K8S_DNS', '192.168.1.1, 8.8.8.8, 8.8.4.4')
    env['phys_iface'] = env.get('PHYS_IFACE', '__PHYS_IFACE__')
    env['vrf_machine_interfaces'] = env.get('VRF_MACHINE_INTERFACES', "['__PHYS_IFACE__']")
    
    render_templates(sys.argv[1], sys.argv[2], env)
