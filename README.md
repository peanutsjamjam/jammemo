# jam memo

シンプルなメモアプリ。左に一覧、右に編集エリア。メモはサーバーに保存するので、
どの端末からでも同じ内容が見える。

公開URL: https://peanutsjamjam.jp/~sugawara/jammemo/

実験用アプリなので、本番用のサイトは無い（このディレクトリが唯一の配信元）。

## 構成

- フロント: React + TypeScript + Vite（`dist/` に本番ビルド）
- バックエンド: `api.cgi`（Perl CGI）。メモは `memo_data/` にテキストファイルで保存
- ログイン情報: PostgreSQL の `jammemo` データベース（`users` / `sessions`）
- 認証（ログイン・セッション・パスワードのハッシュ）は共通ライブラリ
  [pjj-perl5](https://github.com/peanutsjamjam/pjj-perl5)（`PJJ::*`）を使う。このアプリは新規登録が無いので、
  `PJJ->init` の `auth_actions` を `login` / `logout` / `me` の 3 つに絞っている

## ログイン

メモの読み書きにはログインが必要。**新規登録の UI は無く**、アカウントは DB へ
直接入れる。手順は [`ddl/README.md`](ddl/README.md) を参照。

```sh
./ddl/passwd.pl you@example.com yourname | psql -d jammemo
```

`ddl/passwd.pl` も `api.cgi` と同じ `PJJ::Crypt` で PBKDF2 を計算するので、
両者のハッシュがずれることはない。

## 開発

```sh
npm install
npm run dev      # 開発サーバー
npm run build    # dist/ を更新 = 公開サイトに反映
npm run lint
```

`api.cgi` はビルド不要で、編集すると即反映される。

動かすには共通ライブラリ [pjj-perl5](https://github.com/peanutsjamjam/pjj-perl5) が要る。
clone して、`env.pl`（git 管理外）の `$main::PJJ_LIB` にその場所を書く:

```sh
git clone https://github.com/peanutsjamjam/pjj-perl5.git /path/to/perl5
cp env.pl.example env.pl
```

詳しい設計と経緯は [`DEVELOPMENT.md`](DEVELOPMENT.md) を参照。
