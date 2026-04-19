# selfmade_docker

## Docker を全部作らず、Docker っぽい管理層を Rust で作った

- Rust 製の Docker 風 CLI
- low-level runtime は `youki` を利用
- 今回の到達点は `OCI bundle` を EC2 上で起動して外部疎通まで確認

---

# 何を作ったか

> `mydocker`: OCI bundle を受け取り、コンテナ lifecycle を管理する薄い上位レイヤ

- `mydocker create <bundle>`
- `mydocker start <container_id>`
- `mydocker delete <container_id>`
- `mydocker state <container_id>`
- `mydocker run <bundle>`

最小 state は `/run/mydocker` に保存

---

# どこまで自作したか

```text
mydocker
  ├─ bundle validation
  ├─ container ID / state management
  └─ runtime invocation
         |
         v
       youki
         |
         v
   namespace / cgroup / mount
```

- 自作したのは Docker 的な管理層
- 自作していないのは OCI runtime そのもの
- だから短期間でも「動くところ」まで持っていけた

---

# 動いた成果

- FastAPI アプリを `OCI bundle` 化
- `mydocker run /path/to/bundle` で起動
- Ubuntu on EC2 で `youki` 経由の起動を確認
- 外部から CRUD API の疎通を確認
- bundle 配布のための publish script も追加

確認済みフロー:

```bash
cargo build
./target/debug/mydocker run /home/ubuntu/fastapi-bundle
curl http://<ec2-public-ip>:8000/health
curl http://<ec2-public-ip>:8000/items
```

---

# このプロジェクトの価値

- Docker をブラックボックスにせず、責務で分解して理解できる
- runtime を `youki` に委譲して、管理レイヤ実装に集中できる
- 今回は FastAPI で実証、次は image / network / volume に伸ばせる

## Next

`bundle 入力の管理ツール` から `Docker 風エンジン` に育てる
