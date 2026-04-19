# selfmade_docker 発表メモ

## Slide 1

「Docker そのものを再実装したわけではありません。`youki` を下に置いて、その上の Docker っぽい管理層を Rust で作りました。今回は、EC2 上で FastAPI bundle を起動して外から叩けるところまで持っていきました。」

## Slide 2

「CLI としては `create/start/delete/state/run` を実装しています。ポイントは、bundle を受け取って、container ID と state を管理しつつ、runtime を呼ぶ責務に絞ったことです。」

## Slide 3

「攻めたポイントは、全部を作ろうとしなかったことです。namespace や cgroup の実装は `youki` に任せて、自分は管理層だけ作る。この責務分離で、短い期間でも動くものまで到達できました。」

## Slide 4

「実際にやったのは、FastAPI アプリを OCI bundle にして、`mydocker run` で EC2 上に起動、さらに外から CRUD API を叩いて疎通確認するところまでです。加えて、その bundle を配る publish script も作っています。」

## Slide 5

「今回の成果は、Docker の上位レイヤを Rust で最小実装し、実サービスっぽい FastAPI まで通したことです。次は image、network、volume を足して、より Docker 風のエンジンに育てていきます。」
