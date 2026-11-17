# MegaLoc：画像フォルダから上位5件を検索する

ISR のレンダリング ZIP から DB を保存し、画像検索・一括評価を実行する手順は [ISR_PIPELINE.md](ISR_PIPELINE.md) を参照してください。以下は Python・モデルの初回準備と、従来の1枚検索の手順です。

学習済みMegaLocで画像の特徴ベクトルを作り、クエリ画像に似た参照画像を上位5件表示します。
この手順は、新しいWindows PCでPythonを準備するところから始めます。
既存PCにPythonがあることを前提にはしません。まずはCPUで動かす構成です。

## 必要なもの

| 必要なもの | 用意する方法 |
|---|---|
| Windowsの64-bit環境、Python 3.12 | 下の手順1 |
| PyTorch、torchvision、NumPy、Pillow、huggingface_hub、safetensors | 下の手順2でインストール |
| MegaLocの公式コードと学習済み重み | 最初の検索実行時に自動取得。重みは約915 MB |
| 参照画像5枚以上とクエリ画像1枚 | 自分で用意、または手順4の公開サンプルを取得 |
| 初回のインターネット接続 | Python、ライブラリ、モデル、必要ならサンプル画像の取得に使用 |

GPUは必須ではありません。この手順のCPU版ではCUDAのセットアップは不要です。
初回のダウンロードとインストールには時間がかかります。エラーが出たら、その段階を解決してから先へ進んでください。

## 1. Pythonを準備する（初回のみ）

PowerShellで確認します。

```powershell
py -3.12 --version
```

`Python 3.12.x` と出れば手順2へ進みます。
`python` が見つからなくても `py` が使える場合があります。

`py` が認識されない、またはPython 3.12が見つからない場合：

1. [Python公式のWindowsダウンロードページ](https://www.python.org/downloads/windows/) から **Python install manager** をインストールします。
2. PowerShellを閉じ、新しく開き直します。
3. 次を順番に実行します。`pymanager` はPython install managerを指すコマンドです。

```powershell
pymanager install 3.12
py -3.12 --version
```

`Python 3.12.x` が確認できてから次へ進んでください。
インストール後もコマンドが見つからない場合は、使用しているWindowsユーザーでインストールされているか、PATH・アプリ実行エイリアスを確認します。
Python install managerが利用できないWindows環境の代替手順は、[Python公式のAdvanced installation](https://docs.python.org/3/using/windows.html#advanced-installation)を参照してください。

## 2. プロジェクト専用環境とライブラリを準備する（初回のみ）

GitHubから取得したファイルはZIPのまま実行せず、先に展開します。
`megaloc_search.py` と `requirements-megaloc.txt` が入っているフォルダをエクスプローラーで開き、アドレス欄に `powershell` と入力してEnterを押します。
ここから下は、そのPowerShellで順番に実行してください。

```powershell
$ErrorActionPreference = 'Stop'
$projectDir = (Get-Location).Path

if (-not (Test-Path -LiteralPath "$projectDir\megaloc_search.py" -PathType Leaf)) {
    throw 'megaloc_search.py があるフォルダでPowerShellを開いてください。'
}
if (-not (Test-Path -LiteralPath "$projectDir\requirements-megaloc.txt" -PathType Leaf)) {
    throw 'requirements-megaloc.txt が見つかりません。'
}

py -3.12 -m venv "$projectDir\.venv"
if ($LASTEXITCODE -ne 0) { throw 'Python専用環境の作成に失敗しました。' }

$pythonExe = "$projectDir\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw '専用環境のpython.exeが見つかりません。'
}

& $pythonExe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pipの準備に失敗しました。' }

& $pythonExe -m pip install torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'CPU版PyTorchのインストールに失敗しました。' }

& $pythonExe -m pip install -r "$projectDir\requirements-megaloc.txt"
if ($LASTEXITCODE -ne 0) { throw 'ライブラリのインストールに失敗しました。' }

& $pythonExe -c "import torch, torchvision, numpy, PIL, huggingface_hub, safetensors; print('Setup OK'); print('torch:', torch.__version__); print('torchvision:', torchvision.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'ライブラリの読み込み確認に失敗しました。' }
```

`Setup OK` が表示されたら準備完了です。
`.venv` は、このプロジェクト用のPythonとライブラリを入れるフォルダです。
以後はその `python.exe` を直接指定するため、`python` コマンドのPATH登録や仮想環境の有効化操作に依存しません。
`&` は、変数に保存したプログラムのパスをPowerShellから実行する記号です。

PyTorch 2.13.0・torchvision 0.28.0は、このプロジェクトで推論を確認した組み合わせです。
CPU版の取得元と組み合わせは [PyTorch公式のインストール手順](https://pytorch.org/get-started/previous-versions/#v2130) に従っています。

## 3. 自分の画像で検索する（毎回の実行）

同じプロジェクトフォルダでPowerShellを開きます。
`$referenceDir` と `$queryImage` は実在する画像の場所に変更してください。
画像は別のフォルダやドライブに置いたままでも指定できます。

```powershell
$ErrorActionPreference = 'Stop'
$projectDir = (Get-Location).Path
$pythonExe = "$projectDir\.venv\Scripts\python.exe"

# この2行を自分の画像のパスに変更する
$referenceDir = "$projectDir\data\reference"
$queryImage = "$projectDir\data\query\query.jpg"
$outputDir = "$projectDir\output\my_search"

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw '手順2で専用環境とライブラリを準備してください。'
}
if (-not (Test-Path -LiteralPath "$projectDir\megaloc_search.py" -PathType Leaf)) {
    throw 'プロジェクトフォルダが違います。'
}
if (-not (Test-Path -LiteralPath $referenceDir -PathType Container)) {
    throw "検索対象フォルダがありません: $referenceDir"
}
if (-not (Test-Path -LiteralPath $queryImage -PathType Leaf)) {
    throw "クエリ画像がありません: $queryImage"
}

& $pythonExe "$projectDir\megaloc_search.py" --database "$referenceDir" --query "$queryImage" --out "$outputDir" --device cpu
$searchSucceeded = $?
$reportPath = Join-Path $outputDir 'report.html'
if ($searchSucceeded -and $LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    Invoke-Item -LiteralPath $reportPath
} else {
    throw '検索が完了していません。直前に表示されたエラーを確認してください。'
}
```

- `--database`：検索対象の画像フォルダ。サブフォルダも自動で読み込みます。
- `--query`：検索したい画像1枚。
- `--out`：結果の保存先。同じ場所で再実行すると前回の出力を更新します。
- `--device cpu`：CPUで推論します。

JPEG / PNG / WebP / BMP / TIFFに対応します。
クエリと同じファイル、およびバイト単位で同じコピーは除外します。除外後に5枚以上必要です。
切り抜き・再圧縮された近似コピーは自動除外しません。
出力先は検索対象フォルダの外に置いてください。

最初の実行では公式のモデルコードと学習済み重みを取得し、プロジェクト内の `models` に保存します。
既存モデルがそろっている場合はオフラインで読み込みます。
`Embedded ...` に続いて `Done:` と結果の保存先が表示されれば検索完了です。

## 4. 自分の画像がまだない場合：公開サンプルで確認する

手順2が終わった同じPowerShellで実行します。

```powershell
$ErrorActionPreference = 'Stop'
$projectDir = (Get-Location).Path
$pythonExe = "$projectDir\.venv\Scripts\python.exe"

& $pythonExe "$projectDir\prepare_demo_images.py" --out "$projectDir\data\opencv_demo"
if ($LASTEXITCODE -ne 0) { throw 'サンプル画像の取得に失敗しました。' }

& $pythonExe "$projectDir\megaloc_search.py" --database "$projectDir\data\opencv_demo\reference" --query "$projectDir\data\opencv_demo\query\graf1.png" --out "$projectDir\output\megaloc_demo" --device cpu
$searchSucceeded = $?
$reportPath = "$projectDir\output\megaloc_demo\report.html"
if ($searchSucceeded -and $LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
    Invoke-Item -LiteralPath $reportPath
} else {
    throw 'サンプル検索が完了していません。直前のエラーを確認してください。'
}
```

参照画像15枚とクエリ1枚をOpenCVの公開サンプルから取得します。
出典とハッシュは `data/opencv_demo/sources.json` に保存します。
このデータは動作確認用で、場所認識の精度評価用データセットではありません。
確認済みの結果では `graf1.png` に対する1位は `graf3.png`、類似度は約0.595です。

## エラーの読み方

- **pythonが認識されない**：Pythonが未インストール、PATH未登録、または別ユーザーの環境を使っている可能性があります。手順1から確認します。
- **ModuleNotFoundError**：実行しているPythonにライブラリがありません。手順2で使った `.venv\Scripts\python.exe` でインストールと実行をそろえます。
- **report.htmlが存在しない**：検索が失敗したか、出力先が違います。結果ファイルのエラーより先に出たエラーを解決します。
- **画像がない／5枚未満**：指定したフォルダとクエリを確認します。フォルダ名や画像名は実在するものに変更してください。

PowerShellでコマンド自体が見つからないとき、`$LASTEXITCODE` に前の値が残ることがあります。
このREADMEでは、コマンド実行の成否と出力ファイルの存在も確認してから結果を開きます。

## ファイルの役割

- `megaloc_search.py`：画像読み込み、前処理、MegaLocの推論、類似度計算、上位5件の保存。
- `prepare_demo_images.py`：公開サンプルを取得。自分の画像を使う場合は実行不要。
- `requirements-megaloc.txt`：依存ライブラリの一覧。
- `models`：公式モデルのPythonコードと学習済み重み。初回実行時に取得。
- `.venv`：このPCにインストールしたプロジェクト専用Python環境。
- `output`：結果画像、HTML、CSV、実行条件JSON、特徴ベクトルNPZ。

モデルの重みと、画像から計算した特徴ベクトルは別物です。
毎回すべての入力画像の埋め込みを計算し、保存済み特徴量の自動再利用は行いません。
追加学習・幾何検証・位置や姿勢の推定は行いません。類似度は正解確率ではありません。

## GitHubとNotionへの掲載

GitHubには、検索・DB構築・評価・レポート生成のPythonモジュール、サンプル取得スクリプト、`tests`、`requirements-megaloc.txt`、このREADME、`ISR_PIPELINE.md`、`.gitignore` を共有します。
`models` と `.venv` は各PCで準備します。画像データの `data`、生成結果の `output`、一時ファイルの `tmp` もアップロードしません。
以前のPC固有のフォルダ集約用スクリプトは、検索を実行するためには不要です。

Notionには結果の `top5.png` をアップロードし、クエリ名・参照画像枚数・MegaLoc・コサイン類似度・幾何検証なしを記載します。
このプログラムにNotionへの自動アップロード機能はありません。

## 公式資料

- [PythonのWindows導入](https://docs.python.org/3/using/windows.html)
- [PyTorchの導入](https://pytorch.org/get-started/locally/)
- [MegaLoc公式コード](https://github.com/gmberton/MegaLoc)
- [MegaLocの学習済み重み](https://huggingface.co/gberton/MegaLoc)
- [OpenCVのサンプル画像](https://github.com/opencv/opencv/tree/4.x/samples/data)
