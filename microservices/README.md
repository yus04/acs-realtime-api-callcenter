仮想環境を作成する。
```
python -m venv .venv
```

仮想環境を有効化する。
```
source .venv/bin/activate
```

以下のコマンドで Rust をインストールする。Rust は pydantic_settings のモジュールのインストールに必要。実行後にインストールのオプションを聞かれるので `1) Proceed with Standard installation` を選択する。
```
curl -sSf https://sh.rustup.rs | sh
```

以下のコマンドを実行して Rust のパスを通す。(コマンドは Linux 用)
```
export PATH="$HOME/.cargo/bin:$PATH"
```

Rust のパスが通っていることを確認する。
```
cargo --version
```

Python モジュールをインストールする。
```
pip install -r requirements.txt
```

.env.sample を参考にして .env を作成する。

アプリケーションを起動する。
```
python app.py
```
