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

If you are updating the real FastAPI app for all instances, build the Docker image once and publish a new bundle archive to S3 from one build machine. Do not rebuild the bundle separately on every app EC2 instance.

```bash
scripts/publish_fastapi_bundle.sh \
  --image fastapi-demo:latest \
  --bucket selfmade-docker-bundles-245381852209-apne1 \
  --key bundles/fastapi-bundle.tar.gz
```

On Ubuntu, install missing publish dependencies automatically and then publish:

```bash
scripts/publish_fastapi_bundle.sh \
  --image fastapi-demo:latest \
  --bucket selfmade-docker-bundles-245381852209-apne1 \
  --key bundles/fastapi-bundle.tar.gz \
  --install-missing
```

Check prerequisites first if needed:

```bash
scripts/publish_fastapi_bundle.sh \
  --image fastapi-demo:latest \
  --bucket selfmade-docker-bundles-245381852209-apne1 \
  --key bundles/fastapi-bundle.tar.gz \
  --check-only
```

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

One working path used in manual verification was:

1. build a FastAPI Docker image
2. export it with `docker save`
3. convert it with `skopeo copy docker-archive:... oci:...`
4. unpack it with `umoci unpack`
5. remove the `network` namespace from `config.json`
6. run it with `mydocker`

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

Useful checks during EC2 debugging:

```bash
ss -ltnp | grep 8000
curl http://127.0.0.1:8000/health
curl http://<ec2-public-ip>:8000/health
sudo ufw status
```

Expected results from the validated EC2 flow:

- the app listens on `0.0.0.0:8000`
- `curl http://127.0.0.1:8000/health` returns `{"status":"ok"}`
- `curl http://<ec2-public-ip>:8000/health` returns `{"status":"ok"}`
- if localhost works and public IP hangs, check the EC2 security group first

After the container is up, verify the sample app with HTTP requests. Replace host, port, and payload with the values used by your FastAPI bundle.

```bash
curl http://<ec2-public-ip>:8000/health
curl http://<ec2-public-ip>:8000/items
curl -X POST http://<ec2-public-ip>:8000/items -H 'content-type: application/json' -d '{"name":"demo"}'
curl http://<ec2-public-ip>:8000/items
curl -X PUT http://<ec2-public-ip>:8000/items/1 -H 'content-type: application/json' -d '{"name":"updated"}'
curl -X DELETE http://<ec2-public-ip>:8000/items/1
```
