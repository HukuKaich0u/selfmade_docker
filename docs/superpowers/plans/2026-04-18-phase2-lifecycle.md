# Phase 2 Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `create/start/delete/state` and move `run` onto the same lifecycle path.

**Architecture:** Introduce CLI subcommands and lifecycle-oriented runtime/state helpers. `run` stops calling a dedicated `youki run` path and becomes orchestration over `create` then `start`. `state` reads saved metadata only, and `delete` removes runtime state plus the persisted file.

**Tech Stack:** Rust, cargo, clap, serde, serde_json, assert_cmd, tempfile, youki, OCI bundle

---

## File Structure

- Modify: `src/cli.rs`
- Modify: `src/lib.rs`
- Modify: `src/main.rs`
- Modify: `src/runtime.rs`
- Modify: `src/state.rs`
- Modify: `src/error.rs`
- Modify: `tests/cli_run.rs`
- Modify: `README.md`
- Modify: `examples/fastapi-bundle/README.md`
- Reference only: `docs/superpowers/specs/2026-04-18-phase2-lifecycle-design.md`

## Chunk 1: CLI And State Reads

### Task 1: Add lifecycle subcommands

**Files:**
- Modify: `src/cli.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Write failing tests for `create`, `start`, `delete`, and `state` CLI parsing.
- [ ] Step 2: Run targeted CLI tests and verify they fail on missing subcommands.
- [ ] Step 3: Add clap subcommands and typed args.
- [ ] Step 4: Run targeted tests and verify parsing passes.
- [ ] Step 5: Commit.

### Task 2: Add state read path

**Files:**
- Modify: `src/state.rs`
- Modify: `src/lib.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Write a failing integration test for `state <container_id>` returning saved JSON fields.
- [ ] Step 2: Run the targeted test and verify it fails on missing command behavior.
- [ ] Step 3: Add the smallest public read API and wire the `state` command.
- [ ] Step 4: Run the targeted test.
- [ ] Step 5: Commit.

## Chunk 2: Runtime Lifecycle

### Task 3: Add `youki create`

**Files:**
- Modify: `src/runtime.rs`
- Modify: `src/lib.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Write a failing test that `create <bundle>` saves state and invokes `youki create`.
- [ ] Step 2: Run the targeted test and verify it fails for missing implementation.
- [ ] Step 3: Add a typed create request and runtime wrapper.
- [ ] Step 4: Wire `create` to persist `created` state and call runtime.
- [ ] Step 5: Run the targeted test.
- [ ] Step 6: Commit.

### Task 4: Add `youki start` and move `run`

**Files:**
- Modify: `src/runtime.rs`
- Modify: `src/lib.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Write a failing test that `start <container_id>` invokes `youki start` and ends in `exited`.
- [ ] Step 2: Write a failing test that `run <bundle>` now calls `create` then `start` instead of `run`.
- [ ] Step 3: Run the targeted tests and verify the failures are expected.
- [ ] Step 4: Add a typed start request and shared lifecycle orchestration.
- [ ] Step 5: Remove the dedicated `youki run` execution path from `run`.
- [ ] Step 6: Run the targeted tests.
- [ ] Step 7: Commit.

### Task 5: Add `youki delete`

**Files:**
- Modify: `src/runtime.rs`
- Modify: `src/lib.rs`
- Modify: `src/state.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Write a failing test that `delete <container_id>` invokes `youki delete` and removes the state file.
- [ ] Step 2: Run the targeted test and verify it fails for missing implementation.
- [ ] Step 3: Add a typed delete request and wire the command.
- [ ] Step 4: Remove the saved state file after successful runtime delete.
- [ ] Step 5: Run the targeted test.
- [ ] Step 6: Commit.

## Chunk 3: Docs And Verification

### Task 6: Update docs

**Files:**
- Modify: `README.md`
- Modify: `examples/fastapi-bundle/README.md`

- [ ] Step 1: Document `create/start/delete/state`.
- [ ] Step 2: Document that `run` is implemented as `create + start`.
- [ ] Step 3: Review docs for contradictions with Phase 1 language.
- [ ] Step 4: Commit.

### Task 7: Verify Phase 2

**Files:**
- Modify: docs only if verification reveals mismatch

- [ ] Step 1: Run `cargo fmt --all`.
- [ ] Step 2: Run `cargo test`.
- [ ] Step 3: Run `cargo clippy --all-targets --all-features -- -D warnings`.
- [ ] Step 4: Fix any failures and rerun the failing command.
- [ ] Step 5: Commit.

Unresolved questions:
- none

Plan complete and saved to `docs/superpowers/plans/2026-04-18-phase2-lifecycle.md`. Ready to execute?
