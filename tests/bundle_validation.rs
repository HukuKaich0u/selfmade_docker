use std::fs;

use mydocker::bundle;

#[test]
fn validate_requires_config_json() {
    let temp = tempfile::tempdir().unwrap();
    fs::create_dir(temp.path().join("rootfs")).unwrap();

    let error = bundle::validate(temp.path()).unwrap_err();

    assert!(error.to_string().contains("missing config.json"));
}

#[test]
fn validate_requires_rootfs_directory() {
    let temp = tempfile::tempdir().unwrap();
    fs::write(temp.path().join("config.json"), "{}").unwrap();

    let error = bundle::validate(temp.path()).unwrap_err();

    assert!(error.to_string().contains("missing rootfs directory"));
}

#[test]
fn validate_accepts_minimal_bundle_shape() {
    let temp = tempfile::tempdir().unwrap();
    fs::write(temp.path().join("config.json"), "{}").unwrap();
    fs::create_dir(temp.path().join("rootfs")).unwrap();

    let bundle = bundle::validate(temp.path()).unwrap();

    assert_eq!(bundle.bundle_path, temp.path());
    assert_eq!(bundle.config_path, temp.path().join("config.json"));
    assert_eq!(bundle.rootfs_path, temp.path().join("rootfs"));
}
