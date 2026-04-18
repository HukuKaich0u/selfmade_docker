use assert_cmd::Command;
use predicates::str::contains;
use std::fs;
use std::path::Path;

fn create_bundle() -> tempfile::TempDir {
    let temp = tempfile::tempdir().unwrap();
    fs::write(temp.path().join("config.json"), "{}").unwrap();
    fs::create_dir(temp.path().join("rootfs")).unwrap();
    temp
}

fn install_fake_youki(bin_dir: &std::path::Path, args_log: &std::path::Path, exit_code: i32) {
    let script = format!(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"{}\"\nprintf '__CALL_END__\\n' >> \"{}\"\nexit {}\n",
        args_log.display(),
        args_log.display(),
        exit_code
    );
    install_fake_youki_script(bin_dir, &script);
}

fn install_fake_youki_script(bin_dir: &Path, script: &str) {
    let path = bin_dir.join("youki");
    fs::write(&path, script).unwrap();

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(&path).unwrap().permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&path, perms).unwrap();
    }
}

fn read_invocations(args_log: &std::path::Path) -> Vec<Vec<String>> {
    let content = fs::read_to_string(args_log).unwrap_or_default();
    let mut invocations = Vec::new();
    let mut current = Vec::new();

    for line in content.lines() {
        if line == "__CALL_END__" {
            if !current.is_empty() {
                invocations.push(current);
                current = Vec::new();
            }
        } else {
            current.push(line.to_string());
        }
    }

    if !current.is_empty() {
        invocations.push(current);
    }

    invocations
}

fn prepend_to_path(dir: &std::path::Path) -> std::ffi::OsString {
    let current = std::env::var_os("PATH").unwrap_or_default();
    let mut paths = vec![dir.to_path_buf()];
    paths.extend(std::env::split_paths(&current));
    std::env::join_paths(paths).unwrap()
}

fn install_fake_youki_with_start_failure(bin_dir: &Path, args_log: &Path) {
    let script = format!(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"{}\"\nprintf '__CALL_END__\\n' >> \"{}\"\nif [ \"$1\" = \"start\" ]; then\n  exit 17\nfi\nexit 0\n",
        args_log.display(),
        args_log.display()
    );
    install_fake_youki_script(bin_dir, &script);
}

fn install_fake_youki_with_start_and_delete_failure(bin_dir: &Path, args_log: &Path) {
    let script = format!(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"{}\"\nprintf '__CALL_END__\\n' >> \"{}\"\nif [ \"$1\" = \"start\" ]; then\n  exit 17\nfi\nif [ \"$1\" = \"delete\" ]; then\n  exit 22\nfi\nexit 0\n",
        args_log.display(),
        args_log.display()
    );
    install_fake_youki_script(bin_dir, &script);
}

#[test]
fn help_prints_run_subcommand() {
    Command::cargo_bin("mydocker")
        .unwrap()
        .arg("--help")
        .assert()
        .success()
        .stdout(contains("run"))
        .stdout(contains("create"))
        .stdout(contains("start"))
        .stdout(contains("delete"))
        .stdout(contains("state"));
}

#[test]
fn run_accepts_bundle_path_argument() {
    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["run", "/tmp/bundle"])
        .assert()
        .failure()
        .stderr(contains("missing config.json"));
}

#[test]
fn run_executes_full_phase1_flow() {
    let bundle = create_bundle();
    let state_root = tempfile::tempdir().unwrap();
    let bin_dir = tempfile::tempdir().unwrap();
    let args_log = state_root.path().join("youki-args.txt");
    install_fake_youki(bin_dir.path(), &args_log, 0);

    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["run", bundle.path().to_str().unwrap()])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .success();

    let mut entries = fs::read_dir(state_root.path())
        .unwrap()
        .filter_map(Result::ok)
        .filter(|entry| entry.path().extension().and_then(|ext| ext.to_str()) == Some("json"))
        .collect::<Vec<_>>();
    entries.sort_by_key(|entry| entry.file_name());
    assert_eq!(entries.len(), 1);

    let state_value: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(entries[0].path()).unwrap()).unwrap();
    let container_id = state_value["container_id"].as_str().unwrap();
    assert_eq!(state_value["bundle_path"], bundle.path().to_str().unwrap());
    assert_eq!(state_value["status"], "exited");

    let invocations = read_invocations(&args_log);
    assert_eq!(invocations.len(), 2);
    assert_eq!(
        invocations[0],
        vec![
            "create".to_string(),
            "--bundle".to_string(),
            bundle.path().to_str().unwrap().to_string(),
            container_id.to_string()
        ]
    );
    assert_eq!(
        invocations[1],
        vec!["start".to_string(), container_id.to_string()]
    );
}

#[test]
fn run_surfaces_youki_failures() {
    let bundle = create_bundle();
    let state_root = tempfile::tempdir().unwrap();
    let bin_dir = tempfile::tempdir().unwrap();
    let args_log = state_root.path().join("youki-args.txt");
    install_fake_youki(bin_dir.path(), &args_log, 17);

    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["run", bundle.path().to_str().unwrap()])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .code(17)
        .stderr(contains("failed to run container with youki"))
        .stderr(contains("exit status 17"));

    let mut entries = fs::read_dir(state_root.path())
        .unwrap()
        .filter_map(Result::ok)
        .filter(|entry| entry.path().extension().and_then(|ext| ext.to_str()) == Some("json"))
        .collect::<Vec<_>>();
    entries.sort_by_key(|entry| entry.file_name());
    assert_eq!(entries.len(), 1);

    let state_value: serde_json::Value =
        serde_json::from_str(&fs::read_to_string(entries[0].path()).unwrap()).unwrap();
    assert_eq!(state_value["status"], "runtime_failed");
}

#[test]
fn run_rolls_back_created_container_when_start_fails() {
    let bundle = create_bundle();
    let state_root = tempfile::tempdir().unwrap();
    let bin_dir = tempfile::tempdir().unwrap();
    let args_log = state_root.path().join("youki-args.txt");
    install_fake_youki_with_start_failure(bin_dir.path(), &args_log);

    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["run", bundle.path().to_str().unwrap()])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .code(17)
        .stderr(contains("failed to run container with youki"));

    let json_entries = fs::read_dir(state_root.path())
        .unwrap()
        .filter_map(Result::ok)
        .filter(|entry| entry.path().extension().and_then(|ext| ext.to_str()) == Some("json"))
        .collect::<Vec<_>>();
    assert!(json_entries.is_empty());

    let invocations = read_invocations(&args_log);
    assert_eq!(invocations.len(), 3);
    assert_eq!(invocations[0][0], "create");
    assert_eq!(invocations[1][0], "start");
    assert_eq!(invocations[2][0], "delete");
    assert_eq!(
        invocations[0].last().unwrap(),
        invocations[1].last().unwrap()
    );
    assert_eq!(
        invocations[1].last().unwrap(),
        invocations[2].last().unwrap()
    );
}

#[test]
fn run_reports_when_rollback_cleanup_also_fails() {
    let bundle = create_bundle();
    let state_root = tempfile::tempdir().unwrap();
    let bin_dir = tempfile::tempdir().unwrap();
    let args_log = state_root.path().join("youki-args.txt");
    install_fake_youki_with_start_and_delete_failure(bin_dir.path(), &args_log);

    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["run", bundle.path().to_str().unwrap()])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .code(17)
        .stderr(contains("failed to run container with youki"))
        .stderr(contains("rollback failed"))
        .stderr(contains("exit status 22"));

    let invocations = read_invocations(&args_log);
    assert_eq!(invocations.len(), 3);
    assert_eq!(invocations[0][0], "create");
    assert_eq!(invocations[1][0], "start");
    assert_eq!(invocations[2][0], "delete");
}

#[test]
fn run_reports_missing_youki_binary() {
    let bundle = create_bundle();
    let state_root = tempfile::tempdir().unwrap();

    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["run", bundle.path().to_str().unwrap()])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", "")
        .assert()
        .failure()
        .stderr(contains("failed to run container with youki"))
        .stderr(contains("command not found"));
}

#[test]
fn create_saves_state_and_invokes_youki_create() {
    let bundle = create_bundle();
    let state_root = tempfile::tempdir().unwrap();
    let bin_dir = tempfile::tempdir().unwrap();
    let args_log = state_root.path().join("youki-args.txt");
    install_fake_youki(bin_dir.path(), &args_log, 0);

    let output = Command::cargo_bin("mydocker")
        .unwrap()
        .args(["create", bundle.path().to_str().unwrap()])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();

    let container_id = String::from_utf8(output).unwrap();
    let container_id = container_id.trim();
    assert!(!container_id.is_empty());

    let state_value: serde_json::Value = serde_json::from_str(
        &fs::read_to_string(state_root.path().join(format!("{container_id}.json"))).unwrap(),
    )
    .unwrap();
    assert_eq!(state_value["status"], "created");

    let invocations = read_invocations(&args_log);
    assert_eq!(invocations.len(), 1);
    assert_eq!(
        invocations[0],
        vec![
            "create".to_string(),
            "--bundle".to_string(),
            bundle.path().to_str().unwrap().to_string(),
            container_id.to_string()
        ]
    );
}

#[test]
fn state_prints_saved_record() {
    let bundle = create_bundle();
    let state_root = tempfile::tempdir().unwrap();
    let bin_dir = tempfile::tempdir().unwrap();
    let args_log = state_root.path().join("youki-args.txt");
    install_fake_youki(bin_dir.path(), &args_log, 0);

    let create_output = Command::cargo_bin("mydocker")
        .unwrap()
        .args(["create", bundle.path().to_str().unwrap()])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let container_id = String::from_utf8(create_output).unwrap();
    let container_id = container_id.trim().to_string();

    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["state", &container_id])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .assert()
        .success()
        .stdout(contains(&container_id))
        .stdout(contains("\"status\": \"created\""));
}

#[test]
fn start_invokes_youki_start_and_marks_exited() {
    let bundle = create_bundle();
    let state_root = tempfile::tempdir().unwrap();
    let bin_dir = tempfile::tempdir().unwrap();
    let args_log = state_root.path().join("youki-args.txt");
    install_fake_youki(bin_dir.path(), &args_log, 0);

    let create_output = Command::cargo_bin("mydocker")
        .unwrap()
        .args(["create", bundle.path().to_str().unwrap()])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let container_id = String::from_utf8(create_output).unwrap();
    let container_id = container_id.trim().to_string();

    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["start", &container_id])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .success();

    let state_value: serde_json::Value = serde_json::from_str(
        &fs::read_to_string(state_root.path().join(format!("{container_id}.json"))).unwrap(),
    )
    .unwrap();
    assert_eq!(state_value["status"], "exited");

    let invocations = read_invocations(&args_log);
    assert_eq!(invocations.len(), 2);
    assert_eq!(invocations[1], vec!["start".to_string(), container_id]);
}

#[test]
fn delete_invokes_youki_delete_and_removes_state_file() {
    let bundle = create_bundle();
    let state_root = tempfile::tempdir().unwrap();
    let bin_dir = tempfile::tempdir().unwrap();
    let args_log = state_root.path().join("youki-args.txt");
    install_fake_youki(bin_dir.path(), &args_log, 0);

    let create_output = Command::cargo_bin("mydocker")
        .unwrap()
        .args(["create", bundle.path().to_str().unwrap()])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .success()
        .get_output()
        .stdout
        .clone();
    let container_id = String::from_utf8(create_output).unwrap();
    let container_id = container_id.trim().to_string();
    let state_file = state_root.path().join(format!("{container_id}.json"));
    assert!(state_file.exists());

    Command::cargo_bin("mydocker")
        .unwrap()
        .args(["delete", &container_id])
        .env("MYDOCKER_STATE_ROOT", state_root.path())
        .env("PATH", prepend_to_path(bin_dir.path()))
        .assert()
        .success();

    assert!(!state_file.exists());

    let invocations = read_invocations(&args_log);
    assert_eq!(invocations.len(), 2);
    assert_eq!(invocations[1], vec!["delete".to_string(), container_id]);
}
