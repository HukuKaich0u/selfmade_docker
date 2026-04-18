# Phase 1 Hardening Before Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Phase 1 runner enough to validate it on EC2 and leave the codebase ready for `create/start/state/delete` work.

**Architecture:** Keep `run` as the only user-facing command in this plan. First tighten state and runtime boundaries without adding Phase 2 commands, then validate the real EC2 flow, then do the smallest internal refactor needed so Phase 2 can split `run` into clearer lifecycle pieces.

**Tech Stack:** Rust, cargo, clap, serde, serde_json, assert_cmd, tempfile, youki, OCI bundle, Ubuntu EC2

---

## File Structure

- Modify: `src/lib.rs`
- Modify: `src/runtime.rs`
- Modify: `src/state.rs`
- Modify: `src/error.rs`
- Modify: `tests/cli_run.rs`
- Modify: `README.md`
- Modify: `examples/fastapi-bundle/README.md`
- Reference only: `docs/superpowers/specs/2026-04-18-selfmade-docker-engine-design.md`

## Chunk 1: Phase 1 Tightening

### Task 1: Finalize Phase 1 state transitions

**Files:**
- Modify: `src/state.rs`
- Modify: `src/lib.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Add a failing test for successful `run` writing the final success status instead of leaving `created`.
- [ ] Step 2: Run `cargo test --test cli_run run_executes_full_phase1_flow` and verify the failure is the expected status mismatch.
- [ ] Step 3: Add the smallest status model needed for Phase 1 completion, for example `created`, `running` or `exited`, and `runtime_failed`.
- [ ] Step 4: Update the run flow so state transitions are explicit and written in one place.
- [ ] Step 5: Run `cargo test --test cli_run`.
- [ ] Step 6: Commit.

### Task 2: Isolate runtime argument building

**Files:**
- Modify: `src/runtime.rs`
- Modify: `src/lib.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Add a failing test that asserts the exact `youki run` argument shape built by the runtime layer.
- [ ] Step 2: Run the targeted test and verify the failure comes from missing argument-builder structure.
- [ ] Step 3: Extract a small typed runtime request or argument builder that owns `bundle_path` and `container_id`.
- [ ] Step 4: Keep `run_youki` thin so future `create/start/delete/state` wrappers can reuse the same boundary.
- [ ] Step 5: Run `cargo test --test cli_run`.
- [ ] Step 6: Commit.

### Task 3: Tighten user-facing failures

**Files:**
- Modify: `src/error.rs`
- Modify: `src/runtime.rs`
- Modify: `src/state.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Add a failing test for missing `youki` and one for non-zero runtime exit with clear CLI messages.
- [ ] Step 2: Run the targeted tests and verify they fail for the expected wording gap.
- [ ] Step 3: Normalize user-facing errors so they say what failed and where, without leaking unnecessary internals.
- [ ] Step 4: Run `cargo test --test cli_run`.
- [ ] Step 5: Commit.

## Chunk 2: EC2 Validation And Docs

### Task 4: Execute EC2 smoke

**Files:**
- Modify: `README.md` if gaps found
- Modify: `examples/fastapi-bundle/README.md` if gaps found

- [ ] Step 1: Build the current binary with `cargo build`.
- [ ] Step 2: Copy the binary and FastAPI OCI bundle to Ubuntu EC2.
- [ ] Step 3: Verify `youki` with `which youki` and `youki --help`.
- [ ] Step 4: Run `mydocker run <bundle>` on EC2 and record the saved state file plus exit behavior.
- [ ] Step 5: Run the external CRUD smoke against the EC2 public endpoint.
- [ ] Step 6: Commit doc changes only if the real run exposed missing prerequisites or misleading wording.

### Task 5: Lock docs to observed behavior

**Files:**
- Modify: `README.md`
- Modify: `examples/fastapi-bundle/README.md`

- [ ] Step 1: Update the docs to match the final Phase 1 state transition names and saved fields.
- [ ] Step 2: Update the EC2 steps so they match the real working command flow.
- [ ] Step 3: Add any required host prerequisites discovered during smoke, especially networking and permissions.
- [ ] Step 4: Re-read README and example doc together for contradictions.
- [ ] Step 5: Commit.

## Chunk 3: Phase 2 Entry Preparation

### Task 6: Separate run orchestration from lifecycle primitives

**Files:**
- Modify: `src/lib.rs`
- Modify: `src/runtime.rs`
- Modify: `src/state.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Add a failing test around the smallest reusable lifecycle boundary, for example persisting state before runtime invocation and updating state after runtime completion.
- [ ] Step 2: Run the targeted test and verify the failure points to missing orchestration separation.
- [ ] Step 3: Extract minimal internal helpers so `run` becomes orchestration over reusable state and runtime primitives.
- [ ] Step 4: Do not add `create/start/delete/state` commands yet.
- [ ] Step 5: Run `cargo test`.
- [ ] Step 6: Commit.

### Task 7: Prepare state schema for Phase 2 reads

**Files:**
- Modify: `src/state.rs`
- Modify: `tests/cli_run.rs`

- [ ] Step 1: Add a failing test for reading an existing state record back from disk.
- [ ] Step 2: Run the targeted test and verify the failure is due to missing read API.
- [ ] Step 3: Add the smallest read API needed for later `state` command work.
- [ ] Step 4: Keep the schema backward-compatible with the files already written in Phase 1.
- [ ] Step 5: Run `cargo test`.
- [ ] Step 6: Commit.

## Chunk 4: Verification

### Task 8: Full verification before Phase 2

**Files:**
- Modify: docs only if verification reveals mismatch

- [ ] Step 1: Run `cargo fmt --all`.
- [ ] Step 2: Run `cargo test`.
- [ ] Step 3: Run `cargo clippy --all-targets --all-features -- -D warnings`.
- [ ] Step 4: If EC2 smoke was rerun after code changes, re-check the documented command flow.
- [ ] Step 5: Fix any issues and rerun the failing verification command.
- [ ] Step 6: Commit.

Unresolved questions:
- none

Plan complete and saved to `docs/superpowers/plans/2026-04-18-phase1-hardening-before-phase2.md`. Ready to execute?
