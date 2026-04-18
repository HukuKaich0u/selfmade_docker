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

## Phase 1 Behavior

Phase 1 の CLI は `mydocker run <bundle>` のみを提供します。

- `config.json` と `rootfs/` の存在を確認する
- `youki run` を外部 runtime として呼び出す
- `/run/mydocker` 配下に最小 state を保存する

Phase 1 で保存する最小 state:

- `container_id`
- `bundle_path`
- `status`

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

## EC2 Smoke

Ubuntu EC2 での手順は次を前提とします。

- `youki` が `PATH` 上にある
- FastAPI bundle が事前に用意されている
- セキュリティグループとホスト側設定でアプリの listen port が開いている

確認コマンド:

```bash
which youki
youki --help
./target/debug/mydocker run /path/to/fastapi-bundle
```

外部疎通の例:

```bash
curl http://<ec2-public-ip>:8000/health
curl -X POST http://<ec2-public-ip>:8000/items -H 'content-type: application/json' -d '{"name":"demo"}'
curl http://<ec2-public-ip>:8000/items
curl -X PUT http://<ec2-public-ip>:8000/items/1 -H 'content-type: application/json' -d '{"name":"updated"}'
curl -X DELETE http://<ec2-public-ip>:8000/items/1
```

## Docs

- Spec: [`docs/superpowers/specs/2026-04-18-selfmade-docker-engine-design.md`](docs/superpowers/specs/2026-04-18-selfmade-docker-engine-design.md)
- Plan: [`docs/superpowers/plans/2026-04-18-phase1-youki-engine.md`](docs/superpowers/plans/2026-04-18-phase1-youki-engine.md)
- Example Bundle: [`examples/fastapi-bundle/README.md`](examples/fastapi-bundle/README.md)
