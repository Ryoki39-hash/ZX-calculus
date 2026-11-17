# ZX-calculus Graduation Research

**研究テーマ：どのような回路にZX最適化が有効で、どのような回路では改善しないのか**

English working title: **Circuit-Dependent Effectiveness of ZX-Calculus-Based Quantum Circuit Optimization**

## 研究計画

**[研究計画と段階別ロードマップを開く](docs/research_plan.md)**

教授との相談に基づく2026年11月17日の改訂計画です。回路の種類・規模・構造による最適化効果の違いを主題とし、Forward／Reverseの比較は副実験として扱います。以前の「30シード先行」「抽出戦略の自動選択モデル」の計画より、この改訂計画を優先します。

| 段階 | 目的 | 作業の順序 | 主な成果物 |
| --- | --- | --- | --- |
| **第1段階：幅広い回路比較** | 有効例・無効例・トレードオフを探す | 仕様固定 → 入力準備 → 小規模な動作確認 → 33入力の比較 → 全体集計 → 対照例選択 → 次の仮説を固定 | 全入力比較表、ファミリー別集計、対照例候補 |
| **第2段階：対照例の詳細検証** | 傾向の再現性と構造上の違いを調べる | 仮説定義 → 新入力で再検証 → 要因を変えた比較 → 処理途中の追跡 → 必要な副実験 → ケーススタディ → 卒論の結論 | 追加検証、2〜3件の対照例、適用範囲と限界 |

各作業にはS1-1〜S1-7、S2-1〜S2-7のIDを付けています。詳細な実施内容、成果物、完了条件、チェック欄は[研究計画](docs/research_plan.md)を参照してください。

## 最初に比較する内容

初期案はQFT、Toffoli ladder、位相回路、反復Pauli回転回路、ランダムClifford＋Tの**5ファミリー・33入力**です。入力条件は実行前に固定します。

各入力について **Original／Gate-only／ZX-F2／ZX-R2** を比較し、主な基準はGate-onlyとします。T-count、2Q、depth、最適化時間、等価性を記録します。一般角を含むQFTは、Clifford＋T近似合成を行わない限りT-countをN/Aとし、主に2Q・depthを評価します。

**直近の着手順：** 比較仕様と環境を固定し（S1-1）、入力一覧を作成し（S1-2）、各ファミリー1入力で検証と保存を確認してから（S1-3）、33入力を実行します（S1-4）。

## 計画と実測記録の区別

2026年11月17日の計画追加時点で、33入力の比較と第2段階は**今後の作業**です。このドキュメント追加では実験を実行していません。

| 資料 | 内容 |
| --- | --- |
| [研究計画](docs/research_plan.md) | 改訂後の目的、二段階の手順、評価方法、卒論構成 |
| [既存8回路パイロット](benchmarks/pilot-direction-only-8/README.md) | 共通ZXグラフからF2/R2を比較した以前の実験と制約 |
| [既存パイロットCSV](benchmarks/pilot-direction-only-8/pyzx_direction_results.csv) | 以前の実測値。新計画のGate-only比較ではない |
| [研究日誌](research_log/) | 日付ごとのGoal、Experiment、Results、Discussion、Next Actions |

過去のCSVと日誌は履歴として保存します。新しい実行は別run_idで記録し、既存の計測値を上書きしません。計画の保存は、実験の自動実行やZX Research Studioとの同期を意味しません。
