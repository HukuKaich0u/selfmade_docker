# Phase 1 Youki Engine Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal Rust CLI that accepts an OCI bundle, invokes `youki run`, saves minimal container state, and reaches a working FastAPI CRUD container on Ubuntu EC2.

**Architecture:** The project is a thin Docker-like management layer, not a low-level runtime. Phase 1 exposes only `mydocker run <bundle>`, validates the bundle shape, allocates a container ID, writes minimal state under `/run/mydocker` with a test override, shells out to `youki run`, and maps runtime failures into user-facing CLI errors. Later `create/start/delete/state` expansion remains possible, but is out of scope here.

**Tech Stack:** Rust, cargo, clap, serde, serde_json, anyhow or thiserror, tempfile, assert_cmd, predicates, youki, OCI bundle

---

## File Structure

- Create: `Cargo.toml`
- Create: `src/main.rs`
- Create: `src/cli.rs`
- Create: `src/bundle.rs`
- Create: `src/runtime.rs`
- Create: `src/state.rs`
- Create: `src/error.rs`
- Create: `tests/cli_run.rs`
- Create: `tests/bundle_validation.rs`
- Create: `examples/fastapi-bundle/README.md`
- Modify: `README.md`
- Reference only: `docs/superpowers/specs/2026-04-18-selfmade-docker-engine-design.md`
- Reference only: `docs/superpowers/plans/2026-04-18-phase1-youki-engine.md`

## Chunk 1: Bootstrap CLI And Bundle Validation

### Task 1: Initialize crate and help output

**Files:**
- Create: `Cargo.toml`
- Create: `src/main.rs`
- Create: `tests/cli_run.rs`

- [ ] Step 1: Write the failing smoke test in `tests/cli_run.rs`.

```rust
use assert_cmd::Command;
use predicates::str::contains;

#[test]
fn help_prints_run_subcommand() {
    Command::cargo_bin("mydocker")
        .unwrap()
        .arg("--help")
        .assert()
        .success()
        .stdout(contains("run"));
}
```

- [ ] Step 2: Run `cargo test --test cli_run help_prints_run_subcommand` and verify it fails because the crate does not exist yet.
- [ ] Step 3: Create `Cargo.toml` with `clap`, `assert_cmd`, and `predicates`, and create `src/main.rs` with a minimal clap-based binary named `mydocker`.
- [ ] Step 4: Implement minimal `main` so `--help` exits successfully.

```rust
fn main() {
    let _ = cli::Cli::parse();
}
```

- [ ] Step 5: Run `cargo test --test cli_run help_prints_run_subcommand` and verify it passes.
- [ ] Step 6: Commit with `git add Cargo.toml src/main.rs tests/cli_run.rs && git commit -m "feat: bootstrap mydocker cli"`.

### Task 2: Add `run <bundle>` argument parsing

**Files:**
- Create: `src/cli.rs`
- Modify: `src/main.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Add a failing test for parsing `run /tmp/bundle`.

```rust
#[test]
fn run_accepts_bundle_path_argument() {
    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["run", "/tmp/bundle"])
        .assert()
        .failure()
        .stderr(contains("not yet implemented"));
}
```

- [ ] Step 2: Run `cargo test --test cli_run run_accepts_bundle_path_argument` and verify it fails because `run` is not defined.
- [ ] Step 3: Implement `src/cli.rs` with `Cli`, `Commands`, and `RunArgs { bundle: PathBuf }`.
- [ ] Step 4: Update `src/main.rs` to parse `run <bundle>` and return a placeholder error such as `not yet implemented`.
- [ ] Step 5: Run `cargo test --test cli_run run_accepts_bundle_path_argument` and verify it passes.
- [ ] Step 6: Commit with `git add src/main.rs src/cli.rs tests/cli_run.rs && git commit -m "feat: parse run bundle command"`.

### Task 3: Validate OCI bundle shape

**Files:**
- Create: `src/bundle.rs`
- Create: `tests/bundle_validation.rs`
- Modify: `src/main.rs`

- [ ] Step 1: Write failing tests for valid bundle, missing `config.json`, and missing `rootfs`.

```rust
#[test]
fn validate_requires_config_json() { /* temp dir without config.json */ }

#[test]
fn validate_requires_rootfs_directory() { /* temp dir without rootfs */ }

#[test]
fn validate_accepts_minimal_bundle_shape() { /* temp dir with both */ }
```

- [ ] Step 2: Run `cargo test --test bundle_validation` and verify all tests fail because `bundle::validate` does not exist.
- [ ] Step 3: Implement `bundle::validate(path: &Path) -> Result<ValidatedBundle, BundleError>` in `src/bundle.rs`.
- [ ] Step 4: Ensure errors mention the missing path, for example `missing config.json` or `missing rootfs directory`.
- [ ] Step 5: Wire `run` to call `bundle::validate` before the placeholder runtime path.
- [ ] Step 6: Run `cargo test --test bundle_validation` and verify all tests pass.
- [ ] Step 7: Commit with `git add src/main.rs src/bundle.rs tests/bundle_validation.rs && git commit -m "feat: validate oci bundle layout"`.

## Chunk 2: Runtime And State Integration

### Task 4: Add minimal state storage

**Files:**
- Create: `src/state.rs`
- Modify: `src/main.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Add a failing test that exercises state creation with a test override directory.

```rust
#[test]
fn run_writes_initial_state_file() {
    // set MYDOCKER_STATE_ROOT to a temp dir
    // assert state file contains container_id, bundle_path, status
}
```

- [ ] Step 2: Run `cargo test --test cli_run run_writes_initial_state_file` and verify it fails because no state module exists.
- [ ] Step 3: Implement `src/state.rs` with a serializable record that stores `container_id`, `bundle_path`, and `status`.
- [ ] Step 4: Implement `StateStore::new()` using `/run/mydocker` by default and `MYDOCKER_STATE_ROOT` for tests.
- [ ] Step 5: Implement `create_initial_state(&ValidatedBundle) -> Result<StateRecord, _>` and persist one JSON file per container ID.
- [ ] Step 6: Run `cargo test --test cli_run run_writes_initial_state_file` and verify it passes.
- [ ] Step 7: Commit with `git add src/main.rs src/state.rs tests/cli_run.rs && git commit -m "feat: persist minimal runtime state"`.

### Task 5: Wrap `youki run`

**Files:**
- Create: `src/runtime.rs`
- Create: `src/error.rs`
- Modify: `src/main.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Add a failing integration-style test that stubs `youki`.

```rust
#[test]
fn run_invokes_youki_run_with_bundle_and_id() {
    // put a fake `youki` executable earlier in PATH
    // capture args written by the fake executable
    // expect `run`, bundle path, and container id
}
```

- [ ] Step 2: Run `cargo test --test cli_run run_invokes_youki_run_with_bundle_and_id` and verify it fails because runtime execution is not implemented.
- [ ] Step 3: Implement `runtime::run_youki(...)` as a thin `std::process::Command` wrapper around `youki run`.
- [ ] Step 4: Implement user-facing runtime errors in `src/error.rs` for command-not-found and non-zero exit status.
- [ ] Step 5: Run `cargo test --test cli_run run_invokes_youki_run_with_bundle_and_id` and verify it passes.
- [ ] Step 6: Commit with `git add src/main.rs src/runtime.rs src/error.rs tests/cli_run.rs && git commit -m "feat: add youki runtime wrapper"`.

### Task 6: Wire `run` end to end

**Files:**
- Modify: `src/main.rs`
- Modify: `src/bundle.rs`
- Modify: `src/runtime.rs`
- Modify: `src/state.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Add a failing end-to-end test that validates bundle, writes initial state, and invokes `youki run`.

```rust
#[test]
fn run_executes_full_phase1_flow() {
    // build temp OCI bundle
    // set fake PATH and MYDOCKER_STATE_ROOT
    // assert state file exists before successful exit
    // assert fake youki received `run`
}
```

- [ ] Step 2: Run `cargo test --test cli_run run_executes_full_phase1_flow` and verify it fails at the first missing behavior.
- [ ] Step 3: Update `main` to orchestrate parse -> validate -> create state -> invoke runtime -> return child exit status.
- [ ] Step 4: On runtime failure, update stored `status` to a failure value before returning the error.
- [ ] Step 5: Run `cargo test --test cli_run` and verify the CLI integration suite passes.
- [ ] Step 6: Commit with `git add src/main.rs src/bundle.rs src/runtime.rs src/state.rs tests/cli_run.rs && git commit -m "feat: wire phase1 run flow"`.

## Chunk 3: FastAPI Bundle And Docs

### Task 7: Document example bundle and runtime boundary

**Files:**
- Create: `examples/fastapi-bundle/README.md`
- Modify: `README.md`

- [ ] Step 1: Document the expected OCI bundle layout with `config.json` and `rootfs/`.
- [ ] Step 2: State that `youki` is an external runtime dependency and not a deliverable of this project.
- [ ] Step 3: Document the minimal state fields persisted in Phase 1: `container_id`, `bundle_path`, `status`.
- [ ] Step 4: Link from `README.md` to `examples/fastapi-bundle/README.md`.
- [ ] Step 5: Review docs for consistency with the spec wording around `youki run` and `/run/mydocker`.
- [ ] Step 6: Commit with `git add README.md examples/fastapi-bundle/README.md && git commit -m "docs: describe phase1 runtime boundary"`.

### Task 8: Document manual EC2 smoke procedure

**Files:**
- Modify: `examples/fastapi-bundle/README.md`
- Modify: `README.md`

- [ ] Step 1: Add manual steps to prepare a FastAPI OCI bundle on Ubuntu EC2.
- [ ] Step 2: Add commands to confirm `youki` availability, for example `which youki` and `youki --help`.
- [ ] Step 3: Add a sample command `mydocker run /path/to/bundle`.
- [ ] Step 4: Add explicit CRUD smoke commands with `curl`, naming the expected endpoint paths used by the sample app.
- [ ] Step 5: Add a note that security groups and host networking must allow inbound traffic to the app port.
- [ ] Step 6: Commit with `git add README.md examples/fastapi-bundle/README.md && git commit -m "docs: add ec2 smoke procedure"`.

## Chunk 4: Verification

### Task 9: Run local verification

**Files:**
- Test: `tests/cli_run.rs`
- Test: `tests/bundle_validation.rs`

- [ ] Step 1: Run `cargo fmt --all`.
- [ ] Step 2: Run `cargo test`.
- [ ] Step 3: Run `cargo clippy --all-targets --all-features -- -D warnings`.
- [ ] Step 4: Fix any failures and re-run the failing command before moving on.
- [ ] Step 5: Re-run `cargo test` after fixes to confirm the full suite still passes.
- [ ] Step 6: Commit with `git add Cargo.toml src tests README.md examples tests && git commit -m "chore: verify phase1 youki engine"`.

### Task 10: Run EC2 smoke

**Files:**
- Modify: `README.md` if EC2-specific gaps are found
- Modify: `examples/fastapi-bundle/README.md` if bundle instructions are incomplete

- [ ] Step 1: Copy the built binary and OCI bundle to Ubuntu EC2.
- [ ] Step 2: Confirm `youki` is installed and reachable.
- [ ] Step 3: Run `mydocker run <bundle>` and record the container ID plus the saved state file path.
- [ ] Step 4: Execute the documented external CRUD smoke with `curl`.
- [ ] Step 5: If the smoke fails, capture the missing prerequisite in docs before retrying.
- [ ] Step 6: Commit any resulting doc fixes with `git add README.md examples/fastapi-bundle/README.md && git commit -m "docs: capture ec2 smoke notes"`.

Plan complete and saved to `docs/superpowers/plans/2026-04-18-phase1-youki-engine.md`. Ready to execute?
