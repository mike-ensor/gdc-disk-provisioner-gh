use serde_json::Value;

pub fn deep_merge(base: &mut Value, override_val: &Value) {
    match (base, override_val) {
        (Value::Object(ref mut base_map), Value::Object(override_map)) => {
            for (k, v) in override_map {
                if base_map.contains_key(k) {
                    deep_merge(base_map.get_mut(k).unwrap(), v);
                } else {
                    base_map.insert(k.clone(), v.clone());
                }
            }
        }
        (base_val, override_val) => {
            *base_val = override_val.clone();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn get_default_global() -> Value {
        json!({
            "vlan": {
                "id": 100,
                "priority": 1
            },
            "dns": ["8.8.8.8", "8.8.4.4"],
            "ntp": "time.google.com",
            "monitoring": {
                "enabled": true,
                "interval_sec": 60
            }
        })
    }

    #[test]
    fn test_global_only() {
        let mut base = get_default_global();
        let fleet_overrides = json!({});
        let machine_overrides = json!({});

        deep_merge(&mut base, &fleet_overrides);
        deep_merge(&mut base, &machine_overrides);

        assert_eq!(base, get_default_global());
        assert_eq!(base["vlan"]["id"], 100);
        assert_eq!(base["monitoring"]["interval_sec"], 60);
    }

    #[test]
    fn test_global_plus_fleet_no_overrides() {
        let mut base = get_default_global();
        let fleet_overrides = json!({});

        deep_merge(&mut base, &fleet_overrides);

        assert_eq!(base, get_default_global());
    }

    #[test]
    fn test_global_plus_fleet_with_new_variable() {
        let mut base = get_default_global();
        let fleet_overrides = json!({
            "nexus_mirror_url": "https://nexus.fleet.example.com"
        });

        deep_merge(&mut base, &fleet_overrides);

        assert_eq!(base["ntp"], "time.google.com");
        assert_eq!(base["vlan"]["id"], 100);
        assert_eq!(base["nexus_mirror_url"], "https://nexus.fleet.example.com");
    }

    #[test]
    fn test_global_plus_fleet_with_overridden_variable() {
        let mut base = get_default_global();
        let fleet_overrides = json!({
            "ntp": "ntp.fleet.google.internal",
            "vlan": {
                "id": 200
            }
        });

        deep_merge(&mut base, &fleet_overrides);

        assert_eq!(base["ntp"], "ntp.fleet.google.internal");
        assert_eq!(base["vlan"]["id"], 200);
        assert_eq!(base["vlan"]["priority"], 1);
        assert_eq!(base["dns"], json!(["8.8.8.8", "8.8.4.4"]));
    }

    #[test]
    fn test_machine_level_override_and_augmentation() {
        let mut base = get_default_global();
        let fleet_overrides = json!({
            "ntp": "ntp.fleet.google.internal",
            "monitoring": {
                "interval_sec": 30
            },
            "fleet_secret": "fleet-token-123"
        });

        let machine_overrides = json!({
            "dns": ["1.1.1.1"],
            "ntp": "ntp.local-node.internal",
            "monitoring": {
                "enabled": false
            },
            "vlan": {
                "id": 999
            },
            "local_debug": true
        });

        deep_merge(&mut base, &fleet_overrides);
        deep_merge(&mut base, &machine_overrides);

        assert_eq!(base["ntp"], "ntp.local-node.internal");
        assert_eq!(base["dns"], json!(["1.1.1.1"]));
        assert_eq!(base["monitoring"]["enabled"], false);
        assert_eq!(base["monitoring"]["interval_sec"], 30);
        assert_eq!(base["vlan"]["id"], 999);
        assert_eq!(base["vlan"]["priority"], 1);
        assert_eq!(base["fleet_secret"], "fleet-token-123");
        assert_eq!(base["local_debug"], true);
    }
}
