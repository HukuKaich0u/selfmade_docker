use crate::bundle::BundleError;
use crate::runtime::RuntimeError;
use crate::state::StateError;
use std::error::Error;
use std::fmt::{Display, Formatter};

#[derive(Debug)]
pub enum AppError {
    Bundle(BundleError),
    Runtime(RuntimeError),
    RunRollback {
        cause: RuntimeError,
        rollback: Box<AppError>,
    },
    State(StateError),
}

impl Display for AppError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Bundle(error) => Display::fmt(error, f),
            Self::Runtime(error) => write!(f, "failed to run container with youki: {error}"),
            Self::RunRollback { cause, rollback } => write!(
                f,
                "failed to run container with youki: {cause}; rollback failed: {rollback}"
            ),
            Self::State(error) => Display::fmt(error, f),
        }
    }
}

impl Error for AppError {}

impl AppError {
    pub fn exit_code(&self) -> i32 {
        match self {
            Self::Runtime(RuntimeError::ExitStatus(code)) => *code,
            Self::RunRollback {
                cause: RuntimeError::ExitStatus(code),
                ..
            } => *code,
            _ => 1,
        }
    }
}

impl From<BundleError> for AppError {
    fn from(value: BundleError) -> Self {
        Self::Bundle(value)
    }
}

impl From<RuntimeError> for AppError {
    fn from(value: RuntimeError) -> Self {
        Self::Runtime(value)
    }
}

impl From<StateError> for AppError {
    fn from(value: StateError) -> Self {
        Self::State(value)
    }
}
