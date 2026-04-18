use std::error::Error;
use std::ffi::OsString;
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
pub struct CreateRequest {
    bundle_path: PathBuf,
    container_id: String,
}

impl CreateRequest {
    pub fn new(bundle_path: &Path, container_id: &str) -> Self {
        Self {
            bundle_path: bundle_path.to_path_buf(),
            container_id: container_id.to_string(),
        }
    }

    pub fn args(&self) -> Vec<OsString> {
        vec![
            OsString::from("create"),
            OsString::from("--bundle"),
            self.bundle_path.as_os_str().to_os_string(),
            OsString::from(&self.container_id),
        ]
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StartRequest {
    container_id: String,
}

impl StartRequest {
    pub fn new(container_id: &str) -> Self {
        Self {
            container_id: container_id.to_string(),
        }
    }

    pub fn args(&self) -> Vec<OsString> {
        vec![OsString::from("start"), OsString::from(&self.container_id)]
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeleteRequest {
    container_id: String,
}

impl DeleteRequest {
    pub fn new(container_id: &str) -> Self {
        Self {
            container_id: container_id.to_string(),
        }
    }

    pub fn args(&self) -> Vec<OsString> {
        vec![OsString::from("delete"), OsString::from(&self.container_id)]
    }
}

fn run_youki_args(args: Vec<OsString>) -> Result<(), RuntimeError> {
    let status = Command::new("youki")
        .args(args)
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

pub fn create_youki(request: &CreateRequest) -> Result<(), RuntimeError> {
    run_youki_args(request.args())
}

pub fn start_youki(request: &StartRequest) -> Result<(), RuntimeError> {
    run_youki_args(request.args())
}

pub fn delete_youki(request: &DeleteRequest) -> Result<(), RuntimeError> {
    run_youki_args(request.args())
}

#[cfg(test)]
mod tests {
    use super::{CreateRequest, DeleteRequest, StartRequest};
    use std::ffi::OsString;
    use std::path::{Path, PathBuf};

    #[test]
    fn create_request_builds_expected_youki_args() {
        let request = CreateRequest::new(Path::new("/tmp/bundle"), "abc123");

        assert_eq!(
            request.args(),
            vec![
                OsString::from("create"),
                OsString::from("--bundle"),
                OsString::from("/tmp/bundle"),
                OsString::from("abc123")
            ]
        );
    }

    #[test]
    fn start_request_builds_expected_youki_args() {
        let request = StartRequest::new("abc123");

        assert_eq!(
            request.args(),
            vec![OsString::from("start"), OsString::from("abc123")]
        );
    }

    #[test]
    fn delete_request_builds_expected_youki_args() {
        let request = DeleteRequest::new("abc123");

        assert_eq!(
            request.args(),
            vec![OsString::from("delete"), OsString::from("abc123")]
        );
    }

    #[cfg(unix)]
    #[test]
    fn create_request_preserves_non_utf8_bundle_path() {
        use std::os::unix::ffi::OsStringExt;

        let path = PathBuf::from(OsString::from_vec(vec![0x66, 0x6f, 0x80, 0x6f]));
        let request = CreateRequest::new(&path, "abc123");
        let args = request.args();

        assert_eq!(args[2], path.into_os_string());
    }
}
