pub mod bundle;
pub mod error;
pub mod runtime;
pub mod state;

use std::path::Path;

pub fn run_bundle(bundle_path: &Path) -> Result<(), error::AppError> {
    let bundle = bundle::validate(bundle_path)?;
    let state_store = state::StateStore::new()?;
    let state = state_store.create_initial_state(&bundle)?;
    let request = runtime::RunRequest::new(&bundle.bundle_path, state.container_id.as_ref());

    finalize_run_result(
        &state_store,
        &state.container_id,
        runtime::run_youki(&request),
    )
}

fn finalize_run_result(
    state_store: &state::StateStore,
    container_id: &state::ContainerId,
    runtime_result: Result<(), runtime::RuntimeError>,
) -> Result<(), error::AppError> {
    match runtime_result {
        Ok(()) => {
            state_store.update_status(container_id.as_ref(), state::StateStatus::Exited)?;
            Ok(())
        }
        Err(error) => {
            state_store.update_status(container_id.as_ref(), state::StateStatus::RuntimeFailed)?;
            Err(error.into())
        }
    }
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
    fn finalize_run_result_marks_exited_on_success() {
        let bundle = create_bundle();
        let state_root = tempfile::tempdir().unwrap();
        unsafe {
            std::env::set_var("MYDOCKER_STATE_ROOT", state_root.path());
        }

        let validated = bundle::validate(bundle.path()).unwrap();
        let store = state::StateStore::new().unwrap();
        let record = store.create_initial_state(&validated).unwrap();

        finalize_run_result(&store, &record.container_id, Ok(())).unwrap();

        let state_value: serde_json::Value = serde_json::from_str(
            &fs::read_to_string(
                state_root
                    .path()
                    .join(format!("{}.json", record.container_id)),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(state_value["status"], "exited");
        unsafe {
            std::env::remove_var("MYDOCKER_STATE_ROOT");
        }
    }

    #[test]
    fn finalize_run_result_marks_runtime_failed_on_failure() {
        let bundle = create_bundle();
        let state_root = tempfile::tempdir().unwrap();
        unsafe {
            std::env::set_var("MYDOCKER_STATE_ROOT", state_root.path());
        }

        let validated = bundle::validate(bundle.path()).unwrap();
        let store = state::StateStore::new().unwrap();
        let record = store.create_initial_state(&validated).unwrap();

        let result = finalize_run_result(
            &store,
            &record.container_id,
            Err(runtime::RuntimeError::ExitStatus(17)),
        );

        assert!(result.is_err());
        let state_value: serde_json::Value = serde_json::from_str(
            &fs::read_to_string(
                state_root
                    .path()
                    .join(format!("{}.json", record.container_id)),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(state_value["status"], "runtime_failed");
        unsafe {
            std::env::remove_var("MYDOCKER_STATE_ROOT");
        }
    }
}
