# jam memo 開発メモ

※ 旧称 chmemo。`peanutsjamjam` にちなんで **jam memo** に改名（公開URL・ディレクトリも `chmemo` → `jammemo` に変更）。

シンプルなメモアプリ。左に一覧、右に編集エリア。メモはサーバーに保存し、どの端末からでも同じ内容が見える。

公開URL: **http://peanutsjamjam.jp/~sugawara/jammemo/**

---

## 全体構成

```
ブラウザ (React SPA)
   │  fetch (GET/POST/PUT/DELETE)
   ▼
api.cgi (Perl CGI)  ──  memo_data/*.txt  (1メモ=1ファイル)
```

- **フロント**: Vite + React + TypeScript。`dist/` に本番ビルド。
- **バックエンド**: `api.cgi`（Perl）。`memo_data/` にテキストファイルで保存。
- **配信**: Apache の UserDir（`~/public_html/jammemo/` → `/~sugawara/jammemo/`）。
- **保存形式**: 1メモ＝1ファイル。ファイル名は `YYYY_MM_DD_NNNN.txt`（日付＋連番、タイトルは使わない）。
  ファイルの **1行目＝タイトル、2行目＝作成日時、3行目＝最終更新日時、4行目以降＝内容**。
  作成/更新日時は epoch 秒でファイル内に持つ（OS のファイルシステム非依存）。

---

## サーバー環境（重要・調査済み）

- OS: Rocky Linux 9.2 / Apache 2.4.62（mod_fcgid）
- ログインシェルは **csh**。`node`/`npm` は **nvm** 管理（Node v22.13.1, npm 11.1.0）。
  - csh で直接使えるよう `~/.cshrc` に PATH を追記済み:
    `setenv PATH $HOME/.nvm/versions/node/v22.13.1/bin:$PATH`
  - ※ Node を更新したらこの行のバージョン番号も更新が必要。
  - Claude(bash) から実行する時は `export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"` で読み込む。
- **PHP は無し**。CGI は使える（`<Directory /home/*/public_html>` で `ExecCGI` 有効、`cgid_module`/`mod_fcgid` あり）。
- 言語: `/usr/local/bin/perl`（5.36, JSON::PP 4.07 あり）、`/usr/bin/python3`（3.9）。
  → API は当初 Python3 で実装後、**Perl に書き換え**た（`/usr/local/bin/perl` 使用）。
- Apache vhost: `/etc/httpd/conf.d/peanutsjamjam_jp.conf`
  - `UserDir public_html`、`AllowOverride FileInfo AuthConfig Limit Indexes`（= .htaccess で mod_rewrite / AddHandler 可）。

---

## 主要ファイル

| ファイル | 役割 |
|----------|------|
| `src/App.tsx` | アプリ本体（一覧・編集・追加・削除・確認モーダル・設定画面） |
| `src/App.css` / `src/index.css` | レイアウトとスタイル（ライト/ダーク対応） |
| `api.cgi` | 保存API（Perl）。GET=一覧 / POST=新規 / PUT=保存 / DELETE=削除 |
| `memo_data/` | メモの保存先（`YYYY_MM_DD_NNNN.txt`） |
| `.htaccess` | `/~sugawara/jammemo/` を `dist/` へ透過配信＋`.cgi` 実行 |
| `vite.config.ts` | `base: '/~sugawara/jammemo/'`（サブパス配信用） |

### .htaccess の仕組み
- ルートと存在しないパスは `dist/` 配下へ rewrite（本番ビルドを配信）。
- 実在ファイル/ディレクトリ（`api.cgi`, `memo_data/` など）はそのまま実行/配信。
- `.cgi` は `AddHandler cgi-script .cgi` で CGI 実行。

### api.cgi のエンドポイント
- `GET`：全メモを JSON 配列 `[{id,title,content,created,updated}]` で返す（id 昇順）。
- `GET ?example=1`：設定プレビュー用サンプル `{title,content}` を返す。
- `POST`：その日の空メモを新規作成し採番、`{id,title,content,created,updated}` を返す。
- `PUT ?id=<id>`：本文 `{title,content}` を保存。`{ok,updated}`（新しい mtime）を返す。
- `DELETE ?id=<id>`：削除。
- id は `^\d{4}_\d{2}_\d{2}_\d{4}$` で検証（パストラバーサル防止）。

### 作成日時 / 更新日時
- `created` / `updated` は **メモファイル内に保存**（2行目=作成, 3行目=更新, epoch 秒）。
  - POST：`created = updated = 現在時刻`。
  - PUT：既存の `created` を引き継ぎ、`updated` のみ現在時刻に更新。
  - これにより OS のファイルシステム（birth time の有無）に依存しない。
- 右画面のタイトル直下に「作成 / 更新」を表示（整形は JS の `formatTime`）。文字は小さめ・薄め。

### 設定プレビュー用サンプル（example.txt）
- `memo_data/example.txt` は設定画面のフォントサイズ確認用サンプル。無ければ `api.cgi` が自動生成（通常 GET 時 / `?example=1` 時）。
- 内容固定：1行目「ヘルシー豚バラ炒め」＋本文4行（豚バラ肉 200g / トマト 1個 / にら 1/2束 / にんにく 1かけ）。
- ID 形式（`YYYY_MM_DD_NNNN`）に合わないので**メモ一覧には出ない**。手で消しても次の GET で再生成される。

---

## 開発・公開フロー

```
cd ~/public_html/jammemo
npm run dev      # ローカル確認 (http://localhost:5173) ※api.cgiは無いのでサーバー保存は不可
npm run build    # dist/ を更新 = 公開サイトに即反映
```

- **公開サイトに反映するには `npm run build` が必要**（dist/ を Apache が配信）。
- ブラウザ確認時はキャッシュに注意（`Ctrl+F5` / `Cmd+Shift+R`）。

---

## これまでの変更履歴（時系列）

1. 環境準備：nvm 既存の Node を csh で使えるよう `~/.cshrc` に PATH 追記。
2. Vite + React + TypeScript の雛形作成、`dist/` ビルド確認。
3. メモアプリ実装（当初は localStorage 保存）。一覧クリックで右に表示、タイトル1行＋本文複数行。
4. Apache UserDir 配下で公開（`base` 設定＋`.htaccess` で `dist/` 透過配信）。
5. 保存先をブラウザ → **サーバー保存**へ。`memo_data/` に1メモ1ファイル、日付＋連番命名。
   API は CGI で実装（PHP が無いため）。
6. API を **Python3 → Perl** に書き換え（`/usr/local/bin/perl` + JSON::PP）。
7. 左上「chmemo」をリンク化（クリックで再読み込み）＋フォントを太く大きく。
8. 削除を確認制に。最初は `window.confirm`、その後 **中央カードの自前モーダル**へ変更。
9. アイコン導入：**lucide-react**（MIT）。削除＝`Trash2`、新規＝`Plus`、設定＝`Settings`。
10. **設定画面を追加**。左下「保存済み」横の歯車（`Settings`）クリックで、右側全体が設定画面に切替（モーダルではない）。一覧クリック／新規作成で設定画面は閉じる。
    - 設定項目：**テーマ**（ライト/ダーク）と**フォントサイズ**（メモのタイトル / メモの本文 / メモ一覧 を個別にスライダー指定、10〜40px）。
    - テーマ切替方式を **メディアクエリ → `<html data-theme>` 属性**へ変更（`index.css`：`:root` がライト、`:root[data-theme='dark']` がダーク）。
    - フォントサイズは CSS 変数 `--title-size` / `--content-size` / `--list-size` を JS から `document.documentElement.style` に設定して適用。
    - 設定は端末ごとの好みなので **localStorage**（キー `jammemo-settings`）に保存。初回はOSのダーク設定に追従。
11. **設定画面にフォントサイズ確認用プレビューを追加**。サンプルは `memo_data/example.txt`（無ければ `api.cgi` が自動生成）を `GET ?example=1` で取得。プレビューのタイトルは `--title-size`、本文は `--content-size` で描画し、スライダー変更が即反映。メモ一覧サイズは左側でリアルタイムに見えるためプレビュー対象外。
12. **作成日時 / 更新日時を表示**。当初は `api.cgi` がファイルシステムの birth time / mtime から付与していたが、OS 依存を避けるため **メモファイル内に保存する方式へ変更**（2行目=作成, 3行目=更新, 4行目以降=本文）。既存ファイルは移行スクリプトで旧→新フォーマットに変換済み。右画面のタイトル直下に「作成 / 更新」を小さく薄く表示し、PUT 保存時は新しい `updated` を返してフロントが即反映。
13. **chmemo → jam memo に改名**（`peanutsjamjam` にちなむ）。表示名（ロゴ・タブ）に加え、公開URL・ディレクトリを `chmemo` → `jammemo` に変更（`.htaccess` RewriteBase / `vite.config.ts` base / localStorage キー `jammemo-settings`）。旧URL `/~sugawara/chmemo/` は無効。

---

## 既知の制約 / TODO 候補

- **同時編集は非対応**（後勝ちで上書き）。個人利用なら問題なし。
- 保存は入力 0.5 秒後のデバウンス（`apiSave`）。
- ソースや `memo_data/` は外部から閲覧可能（本人了承済み）。
- 連番はその日の最大値+1。日付をまたぐと連番はリセット。
- アイコン追加は `import { 名前 } from 'lucide-react'`（名前は lucide.dev で検索）。
- 表示設定（テーマ・フォントサイズ）は **localStorage 保存で端末ごと**。メモ本体のようにサーバー共有はしない。
