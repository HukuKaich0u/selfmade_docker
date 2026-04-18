pub mod bundle;
pub mod error;
pub mod runtime;
pub mod state;

use std::path::Path;

pub fn run_bundle(bundle_path: &Path) -> Result<(), error::AppError> {
    let bundle = bundle::validate(bundle_path)?;
    let state_store = state::StateStore::new()?;
    let state = state_store.create_initial_state(&bundle)?;

    if let Err(error) = runtime::run_youki(&bundle.bundle_path, state.container_id.as_ref()) {
        state_store.update_status(
            state.container_id.as_ref(),
            state::StateStatus::RuntimeFailed,
        )?;
        return Err(error.into());
    }

    Ok(())
}
