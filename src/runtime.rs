use std::error::Error;
use std::fmt::{Display, Formatter};
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
            Self::ExitStatus(code) => write!(f, "youki exited with status {code}"),
            Self::Io(error) => write!(f, "failed to execute youki: {error}"),
        }
    }
}

impl Error for RuntimeError {}

pub fn run_youki(bundle_path: &std::path::Path, container_id: &str) -> Result<(), RuntimeError> {
    let status = Command::new("youki")
        .arg("run")
        .arg("--bundle")
        .arg(bundle_path)
        .arg(container_id)
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
