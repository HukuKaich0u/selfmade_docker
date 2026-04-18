# Phase 2 Lifecycle Design

## Summary

Phase 2 では `mydocker create/start/delete/state` を追加する。
同時に `mydocker run` も内部では `create + start` の合成として扱う。

この段階でも low-level runtime は実装せず、`youki` 呼び出しの管理層に留まる。

## Scope

今回の対象:

- `create <bundle>`
- `start <container_id>`
- `delete <container_id>`
- `state <container_id>`
- `run <bundle>` の内部経路を `create + start` ベースへ移行

今回の対象外:

- daemon 化
- image build
- custom network
- volume/log 管理
- `youki state` への同期問い合わせ

## Command Semantics

### create

- `OCI bundle` を検証する
- `container_id` を払い出す
- state を `created` で保存する
- `youki create` を呼ぶ
- 成功時は `container_id` を標準出力へ返せるようにする

### start

- 既存 state を読む
- `created` 状態のコンテナに対して `youki start` を呼ぶ
- 呼び出し結果に応じて state を更新する
- foreground 実行が終了したら最終状態は `exited` とする

### delete

- 既存 state を読む
- `youki delete` を呼ぶ
- 成功時は state file を削除する

### state

- `mydocker` が保存した state を返す
- Phase 2 では `youki state` を呼ばない

### run

`run <bundle>` は内部的に以下を行う:

1. bundle validate
2. create 相当処理
3. start 相当処理

CLI としては引き続き bundle path を受け取るだけでよい。

## State Model

Phase 2 の最小 state:

- `container_id`
- `bundle_path`
- `status`

今回の status:

- `created`
- `running`
- `exited`
- `runtime_failed`

`deleted` は保持しない。`delete` 成功時は state file を削除する。

## Runtime Boundary

runtime 層は `youki` の lifecycle コマンドを薄くラップする。

最低限の API:

- `create`
- `start`
- `delete`

必要な入力は typed request に寄せる。

## Error Handling

- `youki` 非ゼロ終了は child exit code を CLI に伝播する
- state 不在は利用者向けに明確なメッセージを返す
- bundle 不正は Phase 1 と同様に path を含めて返す

## Success Criteria

- `create/start/delete/state` がローカルテストで通る
- `run` が `create + start` 経路で通る
- `state <container_id>` が保存済み JSON を返す
- `delete <container_id>` 成功後に state file が消える

