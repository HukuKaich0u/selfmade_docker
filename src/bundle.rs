use std::error::Error;
use std::fmt::{Display, Formatter};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedBundle {
    pub bundle_path: PathBuf,
    pub config_path: PathBuf,
    pub rootfs_path: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BundleError {
    message: String,
}

impl BundleError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for BundleError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl Error for BundleError {}

pub fn validate(path: &Path) -> Result<ValidatedBundle, BundleError> {
    let config_path = path.join("config.json");
    if !config_path.is_file() {
        return Err(BundleError::new(format!(
            "missing config.json at {}",
            config_path.display()
        )));
    }

    let rootfs_path = path.join("rootfs");
    if !rootfs_path.is_dir() {
        return Err(BundleError::new(format!(
            "missing rootfs directory at {}",
            rootfs_path.display()
        )));
    }

    Ok(ValidatedBundle {
        bundle_path: path.to_path_buf(),
        config_path,
        rootfs_path,
    })
}
