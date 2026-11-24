# Stage 1 — Broad Benchmark Screening

[研究計画](../../docs/research_plan.md)に基づく、5ファミリー・33入力の探索的比較。各入力について **Original / Gate-only / ZX** の3条件を保存し、結果表は失敗を含めて99行とする。このREADMEは実験手順を記す。実行の成否と測定値は、各runの保存記録で確認する。

## Inputs

すべて測定・リセットを含まないユニタリ回路。サイズは $n=4,6,8$、確率的な2ファミリーのseedは0・1・2とする。

| Family | 固定する生成規則 | 入力数 |
| --- | --- | ---: |
| QFT | 正のFourier位相。末尾のビット順反転SWAPを明示的に含める | 3 |
| Toffoli ladder | $k=0,\ldots,n-3$ の順に $CCX(k,k+1\rightarrow k+2)$ | 3 |
| Phase circuits | 80操作。各操作は確率0.4で位相、0.6でCNOT。位相角は $\{-3,-2,-1,1,2,3\}\pi/4$ から一様に選ぶ。CNOTの制御・標的は異なる量子ビットの順序付き対から一様に選ぶ | 9 |
| Repeated Pauli rotations | 隣接辺 $(k,k+1)$ を昇順に処理。偶数kはZZ、奇数kはXX。$\lfloor k/2\rfloor$ が偶数なら $+\pi/4$、奇数なら $-\pi/4$。ブロック全体を2・4・8回反復 | 9 |
| Random Clifford+T | `CNOT_HAD_PHASE_circuit`、`depth=80`、`p_had=p_t=0.2`、`clifford=False` | 9 |

Pauli回転の規約は $R_P(\theta)=\exp(-i\theta P/2)$。`CNOT_HAD_PHASE_circuit` の`depth`は生成ゲート数であり、評価する論理depthとは区別する。乱数の具体的な選択順序・実装・環境は設定とソースSHAに固定し、保存QASMとハッシュを入力の同一性の基準とする。[説明用回路図](../../docs/circuit_diagrams.md)と、本runの入力ファイルを混同しない。

## Methods and metrics

環境は **Python 3.12.14 / PyZX 0.10.8 / NumPy 2.3.5** を使用する。共通の正規化をN、ゲート整理をBとする。

| Method | 処理 |
| --- | --- |
| Original | 入力Cを共通基底へ分解した $C_0=N(C)$ |
| Gate-only | $N(B(C_0))$。入力はコピーして処理する |
| ZX | $C_0$ → ZX変換 → `full_reduce` → 標準抽出 → N → B → N |

Bは `basic_optimization(..., do_swaps=False)`。ZX抽出は元の向きのみを使用し、`optimize_cnots=2, optimize_czs=True, up_to_perm=False` に固定する。入力の前処理と出力の正規化規約を統一し、抽出直後・整理後の出力を両方保存する。

T-countはClifford+T回路の位相を標準化した後のTとT†の個数。2Qは分解後の **CNOT＋CZ**、depthは同じ基底での論理依存段数とする。一般角を含むQFTのT-countは **null / N/A** とし、非Clifford位相数を実装上のT数へ読み替えない。主な比較基準はGate-onlyで、Original比も併記する。

## Verification and timing

正規化前の入力の行列を参照し、Originalへの分解を含む各出力を検証する。ワイヤ順は固定し、$|q_0\cdots q_{n-1}\rangle$ のq0を最上位ビットとする。許す差は絶対値1の全体位相のみ。`atol=1e-9, rtol=0` を用い、検証方式・残差・状態を保存する。これは数値的確認であり、厳密な記号証明とは区別する。

Gate-onlyとZXは各1回のウォームアップ後に各10反復を計時し、処理順を交互にする。総最適化時間は入力コピーから最終正規化までを通して実測する。共通の入力正規化、資料の取得・直列化・I/O、指標計算、ハッシュ計算、等価性検証は除く。ZX変換、簡約、抽出、整理等の内訳と全反復値も残す。成分の中央値の和を総時間の中央値として扱わない。各計時出力のハッシュを検証済み出力と照合し、不一致ならその出力を独立に検証する。

**Originalには最適化処理を実行しない。** `timing_status=not_applicable`、`timed_repeats=0`、`optimization_ms_*`は未設定となる。空欄を「最適化時間0 ms」と解釈しない。共通の入力正規化時間は`normalization_ms`に別記する。QFTの`t_count`もJSONでは`null`、CSVでは空欄であり、T-countが0という意味ではない。

## Execution and records

リポジトリのルートで、指定のPython環境から実行する。BLASスレッド数はPython起動前に固定する。

```bash
python -m pip install -r benchmarks/broad_screening/requirements.txt
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
python benchmarks/broad_screening/run.py --prepare
python benchmarks/broad_screening/run.py --smoke --run-id YOUR_UNIQUE_SMOKE_ID
python benchmarks/broad_screening/run.py --run-id YOUR_UNIQUE_FULL_RUN_ID
```

`--prepare`は33入力のハッシュを生成・照合して終了し、最適化を実行しない。`--smoke`は各ファミリーから4量子ビットの1入力を選び、5入力×3条件を別runへ保存する。最後のコマンドが33入力の本実行となる。各run IDには新しい名前を使う。

本測定前にコード・設定・マニフェストをコミットする。`code_commit`はGit checkoutの`HEAD`から自動取得する。Git情報を持たないコピーで実行する場合は、同一内容のコミットSHAを明示する。

```bash
python benchmarks/broad_screening/run.py --run-id YOUR_UNIQUE_FULL_RUN_ID --code-commit SOURCE_COMMIT_SHA
```

SHAの自動取得自体は作業ファイルとの一致を検査しないため、未コミットの変更を残した状態で本測定しない。Git情報と`--code-commit`の両方がない本実行は拒否される。

固定設定は[`configs/stage1-standard-v1.json`](../../configs/stage1-standard-v1.json)、入力一覧は[`manifests/stage1-standard-v1.json`](../../manifests/stage1-standard-v1.json)。実行記録は`runs/<run_id>/`に保存する。

| 保存先 | 内容 |
| --- | --- |
| `metadata.json`, `protocol.json` | 実行日時、状態、環境、ソースSHA、設定のコピー |
| `inputs/<circuit_id>.json` | 入力仕様、**元回路と正規化後のQASM文字列**。独立した`.qasm`ファイルではない |
| `graphs/<circuit_id>.json` | ZX簡約前後のグラフと頂点・辺数 |
| `outputs/<circuit_id>.json` | 各条件およびZX整理前のQASM文字列・ハッシュ |
| `results.csv`, `records/<circuit_id>.json` | 集計表と入力単位の途中記録 |
| `timings.json` | 全反復の計時内訳、出力ハッシュ、検証状態 |
| `verification.json`, `verifier_controls.json` | 参照行列との比較・残差、検証器の対照確認 |

失敗した段階の成果物は存在しない場合がある。途中結果とエラーを逐次残し、完了したrunや以前のパイロットを上書きしない。タイムアウト、抽出エラー、未対応、数値不一致、検証不成立を区別し、悪化・失敗した入力も全体表に残す。

## Interpretation

33入力は傾向を探すための探索集合である。同じ入力の時間反復は独立した10回路ではない。ファミリー、規模、ゲート数、密度、位相の重複等が同時に変わるため、この比較だけで構造の因果効果を断定しない。有効例・無効例を選んだ後、新しい入力と条件をそろえた比較で再検証する。結論の範囲は今回のPyZX手順と回路群であり、ZX計算一般の限界や、実機での実行時間・誤り率を測定したという主張には広げない。
