# Selfmade Docker Engine Design

## Summary

本プロジェクトでは、Docker 風のコンテナ管理ツールを Rust で自作する。
ただし、コンテナの実行そのものは OCI runtime である `youki` を利用し、
自前で runtime を実装することは目的としない。

今回の設計対象は、`youki` を背後で利用する最小の Docker 風エンジンである。

## What We Are Building Now

いま作ろうとしているものは、`OCI bundle` を入力として受け取り、`youki` を呼び出してコンテナを起動・管理する最小 CLI である。

最初のユースケースは以下:

- EC2 上の Ubuntu 環境で動く
- FastAPI アプリを含んだ `OCI bundle` を受け取る
- `mydocker run <bundle>` のようなコマンドで起動する
- 外部から CRUD API にアクセスできる

## Final Goal

最終目標は、Rust 製の Docker 風コンテナ管理ツールを作ること。

このツールは将来的に以下を担う:

- コンテナ lifecycle 管理
- bundle / image の取り扱い
- state / metadata の永続化
- `youki` の実行制御
- 必要に応じた network / volume / logs の管理

ただし low-level runtime は `youki` に委譲する。

## Intermediate Goals

### Phase 1

`OCI bundle` を入力に取り、`youki` を通じて FastAPI コンテナを起動し、EC2 外部から CRUD API を利用できる状態にする。

達成条件:

- `mydocker run <bundle>` 相当が動く
- `youki run` ベースでコンテナを起動する
- `youki` を呼び出してコンテナが起動する
- 最小の state を保存できる
- FastAPI の HTTP API に外部から到達できる
- CRUD の最小疎通を確認できる

### Phase 2

最小の lifecycle 管理を持つ。

- `create`
- `start`
- `delete`
- `state`

### Phase 3

Docker 風の管理レイヤを拡張する。

- bundle 生成補助
- image 入力の導入
- metadata 管理
- network / volume / logs の取り扱い

## Explicit Non-Goals

今回の対象外:

- OCI runtime のスクラッチ実装
- namespace / cgroup / mount の低レベル制御を主責務として持つこと
- `youki` の代替 runtime を作ること
- 初回から Docker 互換を広く揃えること

## Recommended Approach

採用方針は「最小 OCI runtime を自作する」ではなく、「`youki` を利用する最小 Docker 風エンジン」を作ること。

理由:

- 目的に対して責務が正しい
- runtime 実装に深入りせず、管理層に集中できる
- 第1段階の成功までが短い
- その後の機能追加でも責務分離を維持しやすい

## Architecture

最初の成果物は Rust 製の単一バイナリ `mydocker` を想定する。

第1段階の主要責務:

- bundle path の受け取り
- `config.json` / `rootfs` の存在確認
- container ID の払い出し
- state 保存先の決定
- 最小 state の保存
- `youki` コマンドの呼び出し
- 子プロセスの終了コードと実行結果の伝播

内部コンポーネント案:

- `cli`
  - サブコマンド引数の受け取り
- `bundle`
  - `OCI bundle` の事前検証
- `runtime`
  - `youki` 呼び出しの薄いラッパ
- `state`
  - container ID, bundle path, pid, status の保存
- `errors`
  - 利用者向けエラー整形

## Phase 1 Execution Flow

`run` の流れ:

1. CLI が bundle path を受け取る
2. bundle validator が `config.json` と `rootfs/` を確認する
3. container ID と state dir を決める
4. `youki` に必要な引数を構築する
5. `youki` を起動する
6. 親プロセスが終了コードとログを扱う
7. 呼び出し結果を CLI の終了コードに反映する

## User-Facing Scope in Phase 1

第1段階で利用者に見せるもの:

- `run` コマンド
- わかりやすい失敗メッセージ
- `container_id`, `bundle_path`, `status` 程度の最小 state 保存
- FastAPI コンテナの起動
- 外部 HTTP 疎通

第1段階でまだ持たないもの:

- `create` / `start` の分離実装
- image build
- volume 管理
- custom network 管理
- Docker 互換 API
- daemon 化

## Deployment Assumption

対象環境は Ubuntu on EC2。

前提:

- `youki` が利用可能
- `OCI bundle` が事前に用意されている
- FastAPI アプリは bundle 内の `rootfs` に含まれている
- 公開ポートに到達できるようホスト側のネットワーク設定が済んでいる

## Success Criteria

第1段階の成功条件:

- Ubuntu EC2 上で `mydocker run <bundle>` を実行できる
- `youki run` を使ってコンテナを起動できる
- `youki` 経由で FastAPI コンテナが起動する
- 最小 state を保存できる
- 外部から CRUD API を利用できる
- このプロジェクトの責務が「runtime 自作」ではなく「`youki` を使う管理層」であると README と spec に明記されている

## Decisions

- 第1段階の `run` 実装は `youki run` を使う
- state は `/run/mydocker` のような一時 state 用ディレクトリ配下に最小限だけ保存する
- 第1段階の bundle 事前検証は `config.json` と `rootfs/` の存在確認までに留める
