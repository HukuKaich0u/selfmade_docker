# FastAPI OCI Bundle Example

Phase 1 assumes an existing OCI bundle for a FastAPI app. `mydocker` does not build images or generate bundles. It validates the bundle layout, saves minimal state, and delegates container execution to `youki`.
Current lifecycle work delegates container execution to `youki create/start/delete`, and `mydocker run` is implemented as `create + start`.

## Expected Bundle Layout

```text
fastapi-bundle/
├── config.json
└── rootfs/
    ├── app/
    └── ...
```

Required entries:

- `config.json`: OCI runtime config file
- `rootfs/`: root filesystem containing the FastAPI app and its runtime dependencies

## Runtime Prerequisites

- Ubuntu on EC2
- `youki` installed and reachable from `PATH`
- inbound traffic allowed to the FastAPI listen port by security group and host firewall
- the OCI bundle prepared in advance

Check runtime availability:

```bash
which youki
youki --help
```

## Phase 1 State

`mydocker run <bundle>` saves one JSON file under `/run/mydocker` by default. Tests can override this with `MYDOCKER_STATE_ROOT`.

Saved fields in Phase 1:

- `container_id`
- `bundle_path`
- `status`

Expected status transitions in Phase 1:

- initial write: `created`
- after `start` begins: `running`
- successful `start` completion: `exited`
- runtime launch or execution failure: `runtime_failed`

## Manual EC2 Smoke

Build the binary locally or on the EC2 host:

```bash
cargo build
```

Run the bundle:

```bash
./target/debug/mydocker run /path/to/fastapi-bundle
```

The equivalent explicit lifecycle flow is:

```bash
container_id=$(./target/debug/mydocker create /path/to/fastapi-bundle)
./target/debug/mydocker state "$container_id"
./target/debug/mydocker start "$container_id"
./target/debug/mydocker delete "$container_id"
```

If the run succeeds, inspect the saved state file under `/run/mydocker` and confirm the final status is `exited`.

After the container is up, verify the sample app with HTTP requests. Replace host, port, and payload with the values used by your FastAPI bundle.

```bash
curl http://<ec2-public-ip>:8000/health
curl -X POST http://<ec2-public-ip>:8000/items -H 'content-type: application/json' -d '{"name":"demo"}'
curl http://<ec2-public-ip>:8000/items
curl -X PUT http://<ec2-public-ip>:8000/items/1 -H 'content-type: application/json' -d '{"name":"updated"}'
curl -X DELETE http://<ec2-public-ip>:8000/items/1
```
