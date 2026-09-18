# gdc-node-diagnostics Usage Examples

## Example 1: Full Diagnostics with Desired State Comparison

**Scenario:** The user asks to diagnose Node 192.168.9.242 to understand why it failed to achieve its desired networking state, despite the Ansible run completing.

**1. Determine MAC Address and Fetch Desired State**
First, SSH into the machine to grab its primary MAC address (`ip link`):
```shell
$ sshpass -p 'troubled-marble-150' ssh temporary-installer@192.168.9.242 'ip link'
...
2: enp1s0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
    link/ether 00:00:01:04:02:d9 brd ff:ff:ff:ff:ff:ff
...
```

Next, fetch the desired state from the Companion API using the retrieved MAC and the `INSTALL_COMPANION_API_KEY` from `local.env`:
```shell
$ curl -s -X GET "https://gdc-companion.ensor-labs.com/v1/machine-info/00:00:01:04:02:d9" -H "Authorization: Bearer <API_KEY>" | jq .
{
  "bmctl_version": "1.35.300-gke.87",
  "hostname": "gdc-extreme-242",
  "network": {
    "management_network": {
      "dhcp_v4": true,
      "dns_servers": ["8.8.8.8", "8.8.4.4"]
    },
    "cluster_network": {
      "vlan_id": 109,
      "dhcp_v4": false,
      "ip_cidr": "172.31.250.12/24",
      "gateway": "172.31.250.1",
      "dns_servers": ["8.8.8.8", "8.8.4.4"]
    }
  },
  "variables": { ... }
}
```

**2. Trigger `gdc-collector` and Retrieve Tarball**
Ensure the latest diagnostics are generated and uploaded:
```shell
$ sshpass -p 'troubled-marble-150' ssh temporary-installer@192.168.9.242 'sudo /usr/local/bin/gdc-collector --companion-url="https://gdc-companion.ensor-labs.com/v1/machine-reports/ingest"'
```
Then copy the generated tarball to your local machine:
```shell
$ sshpass -p 'troubled-marble-150' scp temporary-installer@192.168.9.242:/tmp/gdc-node-diagnostics-*.tar.gz /tmp/gdc-node-242.tar.gz
$ mkdir -p /tmp/gdc-diagnostics-analysis-242
$ tar -xzf /tmp/gdc-node-242.tar.gz -C /tmp/gdc-diagnostics-analysis-242/
```

**3. Inspect Evidence and Compare States**
Examine `/tmp/gdc-diagnostics-analysis-242/<timestamp>/configs/api-lookup-status.json` to confirm the API was successfully reached.

Check `/tmp/gdc-diagnostics-analysis-242/<timestamp>/configs/99-gdc-cluster-network.yaml`. If the `vlan` section is missing, it indicates the network variables were not properly hydrated by Ansible.

Examine `/tmp/gdc-diagnostics-analysis-242/<timestamp>/configs/gdc.fact` to see how Ansible parsed the API payload. If `network` is `null` but the IP CIDR is buried inside `variables.network`, this indicates a mapping deviation in the playbook.

**4. Generate RCA Document**
Produce the final Root Cause Analysis report outlining the precise JSON mismatch and recommending a fix to the Ansible JSON extraction logic (`api_response.json.variables | default(...)`). 

Save this output locally, ensuring the filename captures the IP, ISO version, and a short identifier of the issue. Be sure to include the fetched JSON payload in the report:

```shell
$ cat << 'EOF' > tmp/node-analysis-reports/rca-192.168.9.242-v0.3.39-payload-mapping-failure.md
# Root Cause Analysis - Node 192.168.9.242

## 1. Header
...

## 2. Desired vs Actual State
- **Desired State (Companion API):**
  ```json
  {
    "bmctl_version": "1.35.300-gke.87",
    "hostname": "gdc-extreme-242",
    "network": { ... }
  }
  ```
- **Actual State:**
...
```

