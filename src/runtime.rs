use std::error::Error;
use std::fmt::{Display, Formatter};
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug)]
pub enum RuntimeError {
    CommandNotFound,
    ExitStatus(i32),
    Io(std::io::Error),
}

impl Display for RuntimeError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::CommandNotFound => f.write_str("failed to execute youki: command not found"),
            Self::ExitStatus(code) => write!(f, "youki exited with exit status {code}"),
            Self::Io(error) => write!(f, "failed to execute youki: {error}"),
        }
    }
}

impl Error for RuntimeError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunRequest {
    bundle_path: PathBuf,
    container_id: String,
}

impl RunRequest {
    pub fn new(bundle_path: &Path, container_id: &str) -> Self {
        Self {
            bundle_path: bundle_path.to_path_buf(),
            container_id: container_id.to_string(),
        }
    }

    pub fn args(&self) -> Vec<&str> {
        vec![
            "run",
            "--bundle",
            self.bundle_path.to_str().unwrap_or_default(),
            self.container_id.as_str(),
        ]
    }
}

pub fn run_youki(request: &RunRequest) -> Result<(), RuntimeError> {
    let status = Command::new("youki")
        .args(request.args())
        .status()
        .map_err(|error| match error.kind() {
            std::io::ErrorKind::NotFound => RuntimeError::CommandNotFound,
            _ => RuntimeError::Io(error),
        })?;

    if status.success() {
        return Ok(());
    }

    Err(RuntimeError::ExitStatus(status.code().unwrap_or(1)))
}

#[cfg(test)]
mod tests {
    use super::RunRequest;
    use std::path::Path;

    #[test]
    fn run_request_builds_expected_youki_args() {
        let request = RunRequest::new(Path::new("/tmp/bundle"), "abc123");

        assert_eq!(
            request.args(),
            vec!["run", "--bundle", "/tmp/bundle", "abc123"]
        );
    }
}
