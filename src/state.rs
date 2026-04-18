use crate::bundle::ValidatedBundle;
use serde::{Deserialize, Serialize};
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Debug)]
pub struct StateStore {
    root: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ContainerId(String);

impl AsRef<str> for ContainerId {
    fn as_ref(&self) -> &str {
        &self.0
    }
}

impl Display for ContainerId {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StateStatus {
    Created,
    Exited,
    RuntimeFailed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StateRecord {
    pub container_id: ContainerId,
    pub bundle_path: String,
    pub status: StateStatus,
}

#[derive(Debug)]
pub struct StateError {
    message: String,
}

impl StateError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for StateError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl Error for StateError {}

impl StateStore {
    pub fn new() -> Result<Self, StateError> {
        let root = std::env::var_os("MYDOCKER_STATE_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("/run/mydocker"));
        fs::create_dir_all(&root).map_err(|error| {
            StateError::new(format!(
                "failed to create state directory {}: {error}",
                root.display()
            ))
        })?;
        Ok(Self { root })
    }

    pub fn create_initial_state(
        &self,
        bundle: &ValidatedBundle,
    ) -> Result<StateRecord, StateError> {
        let record = StateRecord {
            container_id: generate_container_id(),
            bundle_path: bundle.bundle_path.display().to_string(),
            status: StateStatus::Created,
        };
        self.write(&record)?;
        Ok(record)
    }

    pub fn update_status(&self, container_id: &str, status: StateStatus) -> Result<(), StateError> {
        let mut record = self.load(container_id)?;
        record.status = status;
        self.write(&record)
    }

    pub fn load(&self, container_id: &str) -> Result<StateRecord, StateError> {
        let path = self.state_file(container_id);
        let content = fs::read_to_string(&path).map_err(|error| {
            StateError::new(format!(
                "failed to read state file {}: {error}",
                path.display()
            ))
        })?;
        serde_json::from_str(&content).map_err(|error| {
            StateError::new(format!(
                "failed to parse state file {}: {error}",
                path.display()
            ))
        })
    }

    fn write(&self, record: &StateRecord) -> Result<(), StateError> {
        let path = self.state_file(record.container_id.as_ref());
        let json = serde_json::to_string_pretty(record).map_err(|error| {
            StateError::new(format!(
                "failed to serialize state for {}: {error}",
                record.container_id
            ))
        })?;
        fs::write(&path, json).map_err(|error| {
            StateError::new(format!(
                "failed to write state file {}: {error}",
                path.display()
            ))
        })
    }

    fn state_file(&self, container_id: &str) -> PathBuf {
        self.root.join(format!("{container_id}.json"))
    }
}

fn generate_container_id() -> ContainerId {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    ContainerId(format!("mydocker-{nanos:x}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn create_bundle() -> tempfile::TempDir {
        let temp = tempfile::tempdir().unwrap();
        fs::write(temp.path().join("config.json"), "{}").unwrap();
        fs::create_dir(temp.path().join("rootfs")).unwrap();
        temp
    }

    #[test]
    fn load_reads_existing_state_record() {
        let bundle = create_bundle();
        let state_root = tempfile::tempdir().unwrap();
        unsafe {
            std::env::set_var("MYDOCKER_STATE_ROOT", state_root.path());
        }

        let validated = crate::bundle::validate(bundle.path()).unwrap();
        let store = StateStore::new().unwrap();
        let created = store.create_initial_state(&validated).unwrap();
        let loaded = store.load(created.container_id.as_ref()).unwrap();

        assert_eq!(loaded, created);

        unsafe {
            std::env::remove_var("MYDOCKER_STATE_ROOT");
        }
    }
}
