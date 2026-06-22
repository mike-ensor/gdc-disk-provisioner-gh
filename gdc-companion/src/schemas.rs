use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
pub struct DiskConfigDTO {
    pub disk_id: String,
    pub size_gib: u64,
}

#[derive(Debug, Deserialize, Clone)]
pub struct MachineCreateDTO {
    pub hostname: String,
    pub customer_id: String,
    pub google_project_id: String,
    pub google_region: String,
    pub mac_address: String,
    pub uuid: Uuid,
    pub cpu_cores: u32,
    pub ram_gib: u32,
    pub disks: Vec<DiskConfigDTO>,
    pub vrf_machine_cidr: String,
    pub vrf_machine_gateway: String,
    pub vrf_machine_dns: Option<Vec<String>>,
    pub vrf_k8s_cidr: String,
    pub vrf_k8s_gateway: String,
    pub vrf_k8s_dns: Option<Vec<String>>,
    pub fleet_id: Uuid,
    pub variables: Value,
}

#[derive(Debug, Serialize, Deserialize, Clone, PartialEq)]
pub struct ResolvedConfigurationDTO {
    pub hostname: String,
    pub customer_id: String,
    pub google_project_id: String,
    pub google_region: String,
    pub google_org_id: String,
    pub fleet_name: String,
    pub cpu_cores: u32,
    pub ram_gib: u32,
    pub disks: Vec<DiskConfigDTO>,
    pub vrf_machine_cidr: String,
    pub vrf_machine_gateway: String,
    pub vrf_machine_dns: Vec<String>,
    pub vrf_k8s_cidr: String,
    pub vrf_k8s_gateway: String,
    pub vrf_k8s_dns: Vec<String>,
    pub variables: Value,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_dto_serialization_flow() {
        let dto = ResolvedConfigurationDTO {
            hostname: "gdc-node-03".to_string(),
            customer_id: "cust-908".to_string(),
            google_project_id: "gdc-prod".to_string(),
            google_region: "us-central1".to_string(),
            google_org_id: "12345678".to_string(),
            fleet_name: "rack1".to_string(),
            cpu_cores: 32,
            ram_gib: 128,
            disks: vec![DiskConfigDTO {
                disk_id: "/dev/sda".to_string(),
                size_gib: 500,
            }],
            vrf_machine_cidr: "192.168.9.11/24".to_string(),
            vrf_machine_gateway: "192.168.9.1".to_string(),
            vrf_machine_dns: vec!["8.8.8.8".to_string()],
            vrf_k8s_cidr: "10.0.0.5/24".to_string(),
            vrf_k8s_gateway: "10.0.0.1".to_string(),
            vrf_k8s_dns: vec!["8.8.4.4".to_string()],
            variables: json!({"vlan": 100}),
        };

        let serialized = serde_json::to_string(&dto).unwrap();
        let deserialized: ResolvedConfigurationDTO = serde_json::from_str(&serialized).unwrap();
        assert_eq!(deserialized, dto);
    }
}
