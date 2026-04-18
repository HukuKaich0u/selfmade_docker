pub mod bundle;
pub mod error;
pub mod runtime;
pub mod state;

use std::path::Path;

pub fn run_bundle(bundle_path: &Path) -> Result<(), error::AppError> {
    let container_id = create_container(bundle_path)?;
    match start_container(container_id.as_ref()) {
        Ok(()) => Ok(()),
        Err(error) => match rollback_run_failure(container_id.as_ref()) {
            Ok(()) => Err(error),
            Err(rollback) => match error {
                error::AppError::Runtime(cause) => Err(error::AppError::RunRollback {
                    cause,
                    rollback: Box::new(rollback),
                }),
                other => Err(other),
            },
        },
    }
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

pub fn create_container(bundle_path: &Path) -> Result<state::ContainerId, error::AppError> {
    let bundle = bundle::validate(bundle_path)?;
    let state_store = state::StateStore::new()?;
    let state = state_store.create_initial_state(&bundle)?;
    let request = runtime::CreateRequest::new(&bundle.bundle_path, state.container_id.as_ref());

    if let Err(error) = runtime::create_youki(&request) {
        state_store.update_status(
            state.container_id.as_ref(),
            state::StateStatus::RuntimeFailed,
        )?;
        return Err(error.into());
    }

    Ok(state.container_id)
}

pub fn start_container(container_id: &str) -> Result<(), error::AppError> {
    let state_store = state::StateStore::new()?;
    let container_id_value: state::ContainerId = container_id.to_string().into();
    state_store.update_status(container_id, state::StateStatus::Running)?;
    let request = runtime::StartRequest::new(container_id);

    finalize_run_result(
        &state_store,
        &container_id_value,
        runtime::start_youki(&request),
    )
}

pub fn delete_container(container_id: &str) -> Result<(), error::AppError> {
    let state_store = state::StateStore::new()?;
    delete_container_with_store(&state_store, container_id)?;
    Ok(())
}

pub fn read_state(container_id: &str) -> Result<state::StateRecord, error::AppError> {
    let state_store = state::StateStore::new()?;
    Ok(state_store.load(container_id)?)
}

fn delete_container_with_store(
    state_store: &state::StateStore,
    container_id: &str,
) -> Result<(), error::AppError> {
    let request = runtime::DeleteRequest::new(container_id);
    runtime::delete_youki(&request)?;
    state_store.delete(container_id)?;
    Ok(())
}

fn rollback_run_failure(container_id: &str) -> Result<(), error::AppError> {
    let state_store = state::StateStore::new()?;
    delete_container_with_store(&state_store, container_id)
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

        let validated = bundle::validate(bundle.path()).unwrap();
        let store = state::StateStore::new_at(state_root.path()).unwrap();
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
    }

    #[test]
    fn finalize_run_result_marks_runtime_failed_on_failure() {
        let bundle = create_bundle();
        let state_root = tempfile::tempdir().unwrap();

        let validated = bundle::validate(bundle.path()).unwrap();
        let store = state::StateStore::new_at(state_root.path()).unwrap();
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
    }
}
