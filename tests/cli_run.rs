use assert_cmd::Command;
use predicates::str::contains;
use std::fs;

fn create_bundle() -> tempfile::TempDir {
    let temp = tempfile::tempdir().unwrap();
    fs::write(temp.path().join("config.json"), "{}").unwrap();
    fs::create_dir(temp.path().join("rootfs")).unwrap();
    temp
}

fn install_fake_youki(bin_dir: &std::path::Path, args_log: &std::path::Path, exit_code: i32) {
    let script = format!(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"{}\"\nexit {}\n",
        args_log.display(),
        exit_code
    );
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

fn prepend_to_path(dir: &std::path::Path) -> std::ffi::OsString {
    let current = std::env::var_os("PATH").unwrap_or_default();
    let mut paths = vec![dir.to_path_buf()];
    paths.extend(std::env::split_paths(&current));
    std::env::join_paths(paths).unwrap()
}

#[test]
fn help_prints_run_subcommand() {
    Command::cargo_bin("mydocker")
        .unwrap()
        .arg("--help")
        .assert()
        .success()
        .stdout(contains("run"));
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
    assert_eq!(state_value["status"], "created");

    let args = fs::read_to_string(args_log).unwrap();
    assert!(args.contains("run"));
    assert!(args.contains(bundle.path().to_str().unwrap()));
    assert!(args.contains(container_id));
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
        .failure()
        .stderr(contains("youki exited with status 17"));

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
