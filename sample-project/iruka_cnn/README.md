# iruka_cnn

登録済みの日本語定型文をイルカ風ホイッスル音へ変換し、受信側は `WAV` 波形だけから `log-mel + CNN` で元の定型文を推定するローカル実装です。

初版は 24 件の定型文を同梱し、`unknown` と `silence` を含む限定語彙分類として動作します。送信側はテンプレートベース生成器、受信側は埋め込み出力付き 2D CNN を採用しています。

## 動作環境

- macOS / Apple Silicon
- M4 Max MacBook Pro を想定
- Python 3.11 以上
- `uv`
- 学習時は `PyTorch + torchaudio`

MPS が使える環境では、学習モデル本体だけでなく `log-mel` 特徴抽出も可能な限り `mps` を使います。clean 学習と clean 評価は既定で feature cache を使うため、通常の学習ループでは WAV 再読込と再特徴抽出を行いません。

## セットアップ

```bash
cd /Users/nano/workspace/contest/hackathon/20260416_progate_aws_iruka/iruka_cnn
uv sync --extra dev
```

## クイックスタート

### 1. 送信側でイルカ風音声を生成

```bash
uv run python sender_cli.py \
  --text "了解しました" \
  --out ./artifacts/send/ack.wav
```

他にも例えば次を試せます。

```bash
uv run python sender_cli.py --text "停止してください" --out ./artifacts/send/stop.wav
uv run python sender_cli.py --text "再開してください" --out ./artifacts/send/resume.wav
uv run python sender_cli.py --text "助けてください" --out ./artifacts/send/help.wav
uv run python sender_cli.py --text "対象を発見しました" --out ./artifacts/send/found.wav
uv run python sender_cli.py --text "対象は見つかりません" --out ./artifacts/send/not_found.wav
uv run python sender_cli.py --text "こちらへ来てください" --out ./artifacts/send/follow.wav
uv run python sender_cli.py --text "充電が必要です" --out ./artifacts/send/charge.wav
uv run python sender_cli.py --text "周囲はクリアです" --out ./artifacts/send/clear.wav
```

利用可能な定型文は [data/phrases.yaml](/Users/nano/workspace/contest/hackathon/20260416_progate_aws_iruka/iruka_cnn/data/phrases.yaml) に入っています。

### 2. 学習用データを生成

軽量確認:

```bash
uv run python generate_dataset.py --config configs/smoke.yaml --overwrite
```

本番寄り:

```bash
uv run python generate_dataset.py --config configs/baseline.yaml --overwrite
```

`generate_dataset.py` は WAV を作るだけでなく、既定で `float16` の log-mel feature cache (`.npy`) も各サンプル横に生成します。

### 3. 学習

学習中は `tqdm` で、データ生成進捗、epoch/batch 進捗、平均 loss、validation 指標、best checkpoint 更新がリアルタイム表示されます。
baseline / smoke ともに既定で `training.num_workers: auto`、`dataset.cache_features: true`、`augmentation.mode: feature` です。通常の学習ループでは WAV 再読込と waveform augment を行わず、キャッシュ済み log-mel を読み込んで MPS 上で feature-space augment を掛けます。

軽量確認:

```bash
uv run python train.py --config configs/smoke.yaml --regen-dataset
```

本番寄り:

```bash
uv run python train.py --config configs/baseline.yaml --regen-dataset
```

学習中グラフを matplotlib で見たい場合だけ、環境変数を付けます。GUI backend が使える環境ではウィンドウを更新しつつ、同じ内容を `artifacts/models/training_live.png` にも上書き保存します。`MPLBACKEND=Agg` や GUI unavailable の環境では、自動で PNG-only に落ちます。

```bash
IRUKA_ENABLE_TRAIN_PLOTS=1 uv run python train.py --config configs/smoke.yaml --regen-dataset
```

headless 環境で明示的に PNG-only にしたい場合:

```bash
IRUKA_ENABLE_TRAIN_PLOTS=1 MPLBACKEND=Agg uv run python train.py --config configs/smoke.yaml --regen-dataset
```

### 4. 単一 WAV を推論

```bash
uv run python receiver_cli.py \
  --in ./artifacts/send/ack.wav \
  --model ./artifacts/models/best.pt
```

`--with-embedding` を付けると、128 次元の埋め込みベクトルも JSON に含めます。

#### 推論結果の見方

`receiver_cli.py` の出力は「最終判定」と「生の分類結果」を分けて見ます。

- `predicted_label`
  受信側が最終的に返すラベルです。通常はまずこれを見ます。
- `predicted_text`
  現状は `predicted_label` と同じです。将来、内部ラベルと表示文言を分ける場合のために残しています。
- `raw_top_label`
  softmax 上で最も高かった生のクラスです。`predicted_label` が `unknown` なのに `raw_top_label` が定型文になっている場合は、「一番それっぽい候補はあるが、閾値を満たさず unknown に落とした」という意味です。
- `confidence`
  `raw_top_label` の softmax スコアです。高いほどそのクラスに寄っています。
- `top_k`
  上位候補一覧です。2 位との差が小さいと曖昧な判定です。
- `unknown`
  最終判定が `unknown` かどうかです。
- `silence`
  最終判定が `silence` かどうかです。
- `embedding`
  `--with-embedding` 指定時のみ出ます。類似度検索や prototype 比較用です。
- `audio_stats`
  入力音声の基本情報です。`rms_dbfs` が極端に低いと `silence` 判定寄りになります。

#### どこを見ればよいか

まずは次の順で確認すると分かりやすいです。

1. `predicted_label`
2. `unknown` / `silence`
3. `confidence`
4. `top_k` の 1 位と 2 位の差

目安:

- `predicted_label` が期待文と一致し、`unknown=false` なら基本的には成功です。
- `confidence` が高く、2 位との差も大きければ、かなり確信を持って分類できています。
- `raw_top_label` は期待文なのに `predicted_label=unknown` の場合は、閾値が厳しすぎるか、音が少し崩れています。
- `silence=true` の場合は分類前段で無音扱いされています。

#### あなたの実行例の読み方

今回の結果:

```json
{
  "predicted_text": "了解しました",
  "predicted_label": "了解しました",
  "raw_top_label": "了解しました",
  "confidence": 0.836509,
  "unknown": false,
  "silence": false
}
```

これは次の意味です。

- モデルの最終回答は `了解しました`
- 生の 1 位候補も `了解しました`
- `unknown` に落とされていない
- `confidence=0.8365` なので十分高い
- 2 位は `送信します` の `0.0163` で、差分は約 `0.8202`

このモデルの保存閾値は今回 `confidence_threshold=0.5`、`margin_threshold=0.02` なので、今回の音は両方を大きく上回っており、「かなり自信を持って正しく認識した」と読めます。

#### Warning について

`torch.functional.py:681` の `UserWarning` は PyTorch の `stft` 内部バッファ再利用に関する警告で、今回の JSON 推論結果そのものが壊れていることを意味しません。まずは JSON の内容を見れば大丈夫です。

### 5. ストリーミング受信 v1 を試す

v1 は「自由文の全部を送る」のではなく、「登録済み定型文だけを抜き出してイルカ音声化する」方式です。

例:

- 入力: `こんにちは、了解しました。元気ですか？停止してください`
- 送るもの: `了解しました`, `停止してください`
- 送らないもの: `こんにちは`, `元気ですか`

#### 1. サンプル WAV を作る

README の中に Python を埋め込まず、実ファイルとして [tools/build_stream_demo.py](/Users/nano/workspace/contest/hackathon/20260416_progate_aws_iruka/iruka_cnn/tools/build_stream_demo.py) を用意しています。

```bash
uv run python tools/build_stream_demo.py
```

このコマンドの意味:

- `uv run python`
  このリポジトリの仮想環境と依存を使って Python を実行します。
- `tools/build_stream_demo.py`
  自由文から登録済み定型文だけを抽出し、ストリーミング用 WAV を作るサンプルプログラムです。

既定値の動作:

- 入力文: `こんにちは、了解しました。元気ですか？停止してください`
- 出力先: `artifacts/send/stream_demo.wav`
- 無音ギャップ: `300ms`
- seed: `7`

出力 JSON の見方:

- `emitted_texts`
  実際に送信対象になった登録済み定型文です。
- `dropped_fragments`
  登録外なので送らなかった文字列です。
- `output_path`
  生成された WAV の保存先です。

入力文や出力先を変えたい場合:

```bash
uv run python tools/build_stream_demo.py \
  --text "了解しました。停止してください" \
  --out ./artifacts/send/my_stream.wav \
  --gap-ms 300 \
  --seed 7
```

#### 2. 受信側で擬似ストリーミング再生する

```bash
uv run python stream_receiver_cli.py \
  --in ./artifacts/send/stream_demo.wav \
  --model ./artifacts/models/best.pt
```

このコマンドの意味:

- `stream_receiver_cli.py`
  WAV を 20ms ごとの小さな音声チャンクに切って、リアルタイム受信のように順次処理します。
- `--in`
  読み込む WAV ファイルです。ここではさきほど作った `stream_demo.wav` を使います。
- `--model`
  学習済み CNN モデルです。

受信結果の見方:

- `segment_id`
  同じ音声区間に属する仮表示と確定表示を結ぶ ID です。
- `label` / `text`
  現時点の認識結果です。現状は同じ文字列です。
- `confidence`
  そのイベント時点の確信度です。
- `is_final`
  `false` なら仮表示、`true` なら無音区切り後の確定表示です。
- `start_ms` / `end_ms`
  ストリーム内でその区間が始まったおおよその時刻です。

受信側のルール:

- 20ms フレームでエネルギーを監視します。
- 既定 `60ms` 連続で音があればセグメント開始とみなします。
- 既定 `240ms` 連続で無音になればセグメント終了とみなします。
- セグメント中は `150ms` ごとに暫定推論します。
- 最低 `700ms` の有音長が溜まり、同じラベルが 3 回連続で安定したときだけ `provisional` を出します。
- セグメント終了時に 1 回だけ全区間を正式推論し、`final` を返します。

要するに、このサンプルで確認できるのは次の 2 点です。

- 送信側が「自由文から登録済み定型文だけを抜き出せる」こと
- 受信側が「その WAV をフレーズ単位に分けて `provisional/final` を返せる」こと

この v1 は「短い無音で区切られたフレーズ列」向けです。区切りなし完全連続ストリームは今の CNN だけでは苦しく、将来は系列モデルへの拡張が必要です。

#### 3. Mac のスピーカー再生とマイク録音で実演する

WAV ファイルを直接 `stream_receiver_cli.py` に渡す代わりに、実際に Mac のスピーカーから音を出し、マイクで拾って認識させる demo も用意しています。実ファイルは [tools/demo_speaker_mic_stream.py](/Users/nano/workspace/contest/hackathon/20260416_progate_aws_iruka/iruka_cnn/tools/demo_speaker_mic_stream.py) です。

まず音声デバイスを見たい場合:

```bash
uv run python tools/demo_speaker_mic_stream.py --list-devices
```

このコマンドの意味:

- `tools/demo_speaker_mic_stream.py`
  生成→再生→録音→ストリーミング認識までを 1 回で通す acoustic demo です。
- `--list-devices`
  利用可能な入力/出力デバイスを表示して終了します。既定デバイス以外を使いたいときの確認用です。

既定デバイスで実行:

```bash
uv run python tools/demo_speaker_mic_stream.py \
  --text "こんにちは、了解しました。元気ですか？停止してください" \
  --model ./artifacts/models/best.pt
```

初回は macOS のマイク権限ダイアログが出ることがあります。拒否すると録音できないので、許可してください。

必要なら入出力デバイスを override できます。

```bash
uv run python tools/demo_speaker_mic_stream.py \
  --text "了解しました。停止してください" \
  --model ./artifacts/models/best.pt \
  --input-device "Built-in Microphone" \
  --output-device "MacBook Pro Speakers"
```

既定値の動作:

- 入力文から登録済み定型文だけを抽出して送信音を作る
- 再生前に `300ms` の無音を付ける
- 再生後も `1200ms` 録音を続ける
- 再生音は `artifacts/send/acoustic_demo_played.wav`
- 録音音は `artifacts/recv/acoustic_demo_recorded.wav`

出力の見方:

- 実行中は `{"type":"event", ...}` が 1 行ずつ流れます。
  `is_final=false` は仮表示、`is_final=true` は確定表示です。
- 最後に `{"type":"summary", ...}` が 1 回出ます。
  `emitted_texts` は送信対象になった定型文、`dropped_fragments` は登録外なので送らなかった部分です。
  `events` には受信側が復元したフレーズ列が入ります。

この demo は「本物のスピーカーとマイク」を使うので、WAV 直結より結果が不安定です。音量が小さすぎる、マイクが遠い、部屋の反響が大きい、といった条件では `unknown` が増えることがあります。

### 6. 音声とスペクトログラムを可視化

任意のタイミングで、波形・線形 spectrogram・mel spectrogram・モデル入力 log-mel を 1 枚の PNG に出せます。既定は PNG 保存のみで、`--show` を付けたときだけ GUI 表示します。

既存 WAV を可視化:

```bash
uv run python visualize_audio_cli.py \
  --wav ./artifacts/send/ack.wav \
  --out ./artifacts/reports/ack_viz.png
```

登録済み定型文をその場で生成して可視化:

```bash
uv run python visualize_audio_cli.py \
  --text "了解しました" \
  --seed 7 \
  --out ./artifacts/reports/ack_gen_viz.png
```

`--wav` は任意の WAV を受けられますが、可視化される waveform/spectrogram は受信モデルに入る前処理後の信号に揃えています。つまり、モデルが実際に見ている形を観察する用途です。

### 7. 評価

クリーン条件:

```bash
uv run python eval.py --config configs/baseline.yaml --split test --condition clean
```

劣化条件:

```bash
uv run python eval.py --config configs/baseline.yaml --split test --condition degraded
```

#### confusion matrix の見方

混同行列画像の `C00`, `C01`, ... はラベル名そのものではなく、ラベル配列のインデックスです。対応順は [artifacts/models/label_vocab.json](/Users/nano/workspace/contest/hackathon/20260416_progate_aws_iruka/iruka_cnn/artifacts/models/label_vocab.json) の `labels` と一致します。

今回の baseline では次の対応です。

- `C00` から `C23`: 24 個の登録済み定型文
- `C24`: `unknown`
- `C25`: `silence`

そのため、test clean の混同行列で `C24` に `320`、`C25` に `160` が見えるのは正常です。これは誤分類が多いという意味ではなく、test split に最初から `unknown=320件`、`silence=160件` 入っているためです。通常の定型文クラスは各 `64件` なので、`unknown` と `silence` だけ対角成分が大きく見えます。

判断の仕方:

- 斜め成分だけに値があり、他が `0` なら完全分類です。
- ある行で斜め以外に数字があれば、その真のクラスが別クラスへ取り違えられています。
- `unknown` 行に他クラス列の値が出ていたら、未登録音を誤って受理しています。

## 出力物

- `artifacts/models/best.pt`: 学習済みモデル
- `artifacts/models/label_vocab.json`: 受信側用ラベル語彙
- `artifacts/models/thresholds.json`: unknown 判定閾値
- `artifacts/models/prototypes.json`: 埋め込み prototype
- `artifacts/reports/*_report.json`: 評価レポート
- `artifacts/reports/*_confusion.png`: confusion matrix

## 主要ディレクトリ

```text
.
├── configs/
├── data/
│   ├── phrases.yaml
│   ├── train/
│   ├── val/
│   └── test/
├── artifacts/
├── src/iruka_cnn/
│   ├── common/
│   ├── sender/
│   ├── receiver/
│   └── training/
├── sender_cli.py
├── receiver_cli.py
├── generate_dataset.py
├── train.py
└── eval.py
```

## 実装メモ

- 送信側は各定型文ごとに固有のホイッスル骨格を持ち、毎回微小揺らぎを入れて完全固定化を避けます。
- 受信側は `WAV` 以外の入力を使いません。
- `unknown` は未登録ホイッスル、破綻音、ノイズ寄りパターンを生成して学習します。
- `silence` は低振幅のフロアノイズ付き無音で学習します。
- 埋め込みは `128` 次元で、将来の prototype 拡張や追加学習に流用できます。
- clean train/eval は cached feature を使い、`degraded` eval のみ waveform degradation を保持しています。

## テスト

```bash
uv run pytest
```
