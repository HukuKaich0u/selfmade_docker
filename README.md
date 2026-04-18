# selfmade_docker

Rust で Docker 風のコンテナ管理ツールを自作するプロジェクトです。

このプロジェクトの目的は、Docker のような上位レイヤを理解しながら自作することです。ただし、コンテナの実行そのものを担う low-level runtime は自前実装しません。OCI runtime として `youki` を利用し、本プロジェクトでは `youki` を呼び出す管理層と周辺機能を実装します。

## Project Goals

### Final Goal

Rust 製の Docker 風コンテナ管理ツールを作る。

- コンテナの lifecycle を管理できる
- OCI bundle や将来的な image 入力を扱える
- runtime として `youki` を呼び出せる
- Docker 的な上位責務を段階的に持てる

### Intermediate Goal

第1段階では、EC2 上で FastAPI アプリのコンテナを起動し、外部から簡単な CRUD API を利用できるところまで到達する。

- 入力は標準的な `OCI bundle`
- 実行には `youki run` を使う
- 最小の state を保存する
- 最初の CLI は `mydocker run <bundle>` 相当を目指す
- FastAPI アプリを起動し、HTTP 経由で CRUD API を確認する

## Non-Goals

- OCI runtime 自体をスクラッチで実装すること
- `runc` / `youki` 相当の low-level runtime を作ること
- 初期段階で Docker の全機能を再現すること

## Scope Boundary

本プロジェクトが担当するもの:

- bundle の受け取りと検証
- container ID / state / metadata 管理
- `youki` 呼び出し
- Docker 風 CLI の実装
- 将来の network / volume / image 管理の土台

本プロジェクトが担当しないもの:

- namespace / cgroup / mount を直接扱う low-level runtime 実装
- OCI runtime spec の完全実装

## Lifecycle Commands

現在の CLI は次を提供します。

- `mydocker create <bundle>`
- `mydocker start <container_id>`
- `mydocker delete <container_id>`
- `mydocker state <container_id>`
- `mydocker run <bundle>`

- `config.json` と `rootfs/` の存在を確認する
- `youki create/start/delete` を外部 runtime として呼び出す
- `/run/mydocker` 配下に最小 state を保存する

`mydocker run <bundle>` は内部的には `create + start` の合成として扱います。

Phase 1 で保存する最小 state:

- `container_id`
- `bundle_path`
- `status`
  - 実行開始直後: `created`
  - 正常終了後: `exited`
  - runtime 失敗時: `runtime_failed`

`youki` はこのプロジェクトの生成物ではなく、事前にインストールされている前提の外部依存です。

## Local Usage

```bash
cargo build
./target/debug/mydocker run /path/to/oci-bundle
```

bundle の最小要件:

```text
bundle/
├── config.json
└── rootfs/
```

## Bundle Publish

`mydocker` は `Dockerfile` や image を直接扱いません。実際に配る前に、FastAPI app を `OCI bundle` に変換して S3 に置く必要があります。

このリポジトリには、そのための script を置いてあります。

```bash
scripts/publish_fastapi_bundle.sh \
  --image fastapi-demo:latest \
  --bucket selfmade-docker-bundles-245381852209-apne1 \
  --key bundles/fastapi-bundle.tar.gz
```

Ubuntu で依存導入から一撃でやりたいとき:

```bash
scripts/publish_fastapi_bundle.sh \
  --image fastapi-demo:latest \
  --bucket selfmade-docker-bundles-245381852209-apne1 \
  --key bundles/fastapi-bundle.tar.gz \
  --install-missing
```

この script がやること:

- `docker save`
- `skopeo copy docker-archive:... oci:...`
- `umoci unpack`
- `config.json` から `network` namespace を除去
- `fastapi-bundle.tar.gz` を作成
- S3 へ upload

どこで実行するか:

- build 用の 1 台のマシンだけで実行する
- 例: 開発用 EC2、CI runner、手元の Linux ホスト
- app を動かす全 EC2 で実行する必要はない

前提コマンド:

- `docker`
- `skopeo`
- `umoci`
- `jq`
- `aws`

前提確認だけ先にしたいとき:

```bash
scripts/publish_fastapi_bundle.sh \
  --image fastapi-demo:latest \
  --bucket selfmade-docker-bundles-245381852209-apne1 \
  --key bundles/fastapi-bundle.tar.gz \
  --check-only
```

足りないコマンドがあれば、script 自体が不足一覧と導入ヒントを表示します。

`--install-missing` は内部的に [scripts/install_bundle_publish_deps.sh](/Users/KokiAoyagi/Documents/repos/personal/selfmade_docker/scripts/install_bundle_publish_deps.sh) を呼び、Ubuntu 上で `docker.io`, `skopeo`, `umoci`, `jq`, `unzip`, AWS CLI v2 を自動導入します。

## EC2 Smoke

Ubuntu EC2 での手順は次を前提とします。

- `youki` が `PATH` 上にある
- FastAPI bundle が事前に用意されている
- セキュリティグループとホスト側設定でアプリの listen port が開いている

今回の実機確認では、FastAPI app を Docker image として作成し、`docker save` + `skopeo copy docker-archive:... oci:...` + `umoci unpack` で `OCI bundle` に変換しました。`mydocker` 自体は bundle を生成しないため、この bundle 準備は外部手順です。

実機で確認した最小フロー:

```bash
which youki
youki --help
cargo build
sudo env "PATH=$PATH" ./target/debug/mydocker run /home/ubuntu/fastapi-bundle
curl http://127.0.0.1:8000/health
curl http://<ec2-public-ip>:8000/health
```

補足:

- FastAPI bundle は host から到達確認するため、`config.json` から `network` namespace を外した
- EC2 上では `ss -ltnp | grep 8000` で `0.0.0.0:8000` listen を確認した
- `ufw` は inactive だったため、外部疎通で詰まる場合は security group を先に確認する
- Launch Template 配備では、bundle 自体は S3 に置き、各 EC2 は起動時にそれを取得する

lifecycle 確認コマンド:

```bash
which youki
youki --help
./target/debug/mydocker create /path/to/fastapi-bundle
./target/debug/mydocker state <container_id>
./target/debug/mydocker start <container_id>
./target/debug/mydocker delete <container_id>
./target/debug/mydocker run /path/to/fastapi-bundle
```

外部疎通の例:

```bash
curl http://<ec2-public-ip>:8000/health
curl http://<ec2-public-ip>:8000/items
curl -X POST http://<ec2-public-ip>:8000/items -H 'content-type: application/json' -d '{"name":"demo"}'
curl http://<ec2-public-ip>:8000/items
curl -X PUT http://<ec2-public-ip>:8000/items/1 -H 'content-type: application/json' -d '{"name":"updated"}'
curl -X DELETE http://<ec2-public-ip>:8000/items/1
```

## Docs

- Spec: [`docs/superpowers/specs/2026-04-18-selfmade-docker-engine-design.md`](docs/superpowers/specs/2026-04-18-selfmade-docker-engine-design.md)
- Plan: [`docs/superpowers/plans/2026-04-18-phase1-youki-engine.md`](docs/superpowers/plans/2026-04-18-phase1-youki-engine.md)
- Example Bundle: [`examples/fastapi-bundle/README.md`](examples/fastapi-bundle/README.md)
