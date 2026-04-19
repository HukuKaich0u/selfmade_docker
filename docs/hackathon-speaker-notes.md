# selfmade_docker x iruka_cnn 発表メモ

## Slide 1

「今回やったのは、Docker 全体を再実装することではなく、Docker の上位管理レイヤだけを Rust で切り出して、その上に CNN 推論 API を載せることです。`mydocker` は bundle を受け取り、container ID を払い出し、state を保存し、runtime を呼び出すところを持っています。その上で `iruka_cnn` の FastAPI worker を載せ、WAV を受けて `log-mel + CNN` で定型文分類する API を動かしました。」

## Slide 2

「`mydocker` の中も分割しています。`cli.rs` がコマンド入口、`bundle.rs` が OCI bundle の検証、`state.rs` が `/run/mydocker` 配下の状態管理、`runtime.rs` が `youki create/start/delete` のラッパです。つまり Docker でいう engine の管理責務は自分で持ちつつ、namespace や cgroup のような low-level runtime だけを `youki` に委譲しています。この責務の切り方が今回の技術的な肝です。」

## Slide 3

「成果としては、CNN モデル込みの FastAPI worker を bundle 化して、`mydocker run` で EC2 上に起動し、`/healthz` と `/infer` まで通しました。ここで言いたいのは、単に CLI を作ったのではなく、ML 推論ワークロードを受け止められるコンテナ管理基盤の最小コアを作れたということです。次は image、network、複数 worker に伸ばしていけます。」
