# プロジェクト名　
Image F Fiji 

複数のnd2ファイルを読み込んで三次元ピアソン係数解析を行うことが可能です。

## 推奨環境

- Python 3.12.6
- Visual Studio Code

## インストール＆起動手順（VS Code使用）

以下の手順を順番に実行してください。

### 手順1 gitコマンドを使用してダウンロード(gitインストール必須)
git clone https://github.com/あなたのユーザー名/リポジトリ名.git

### 手順2 python 3.12.6をインストール(公式インストーラから)
https://www.python.org/downloads/release/python-3126/ 
「Add python.exe to PATH」（Windowsの場合）にチェック

### 手順3 VScodeをダウンロードする

### 手順4 仮想環境の構築
VScode 上で CTRL + SHIFT + P を同時に押し「Python: Create Environment...」→ 「Venv」を選択 → Python 3.12.6 を選択

### 手順5 仮想環境の有効化

#### Windowsの場合コマンドプロンプトに以下のコードを入力し実行
venv\Scripts\activate

#### Mac/Linuxの場合場合コマンドプロンプトに以下のコードを入力し実行
source venv/bin/activate

##### インストール終了後の確認(python 3.12.6と表示されればOK)
python --version

### 手順6 依存パッケージを仮想環境にインストール
pip install -r requirements.txt

### 手順7 アプリケーションの起動
python main.py
