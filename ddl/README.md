# jammemo の DB

ログイン用のユーザー情報を PostgreSQL の `jammemo` データベースに置く。
メモの実体は従来どおり `memo_data/` のテキストファイルで、DB には入らない。

- `users.sql` … アカウント（PBKDF2-HMAC-SHA256 でパスワードを保存）
- `sessions.sql` … ログイン状態。Cookie `jammemo_sid` で受け渡す

`api.cgi` は peer 認証で接続する（UserDir の CGI は suexec により `sugawara` で動くため、
`dbi:Pg:dbname=jammemo` にユーザー名・パスワードなしで繋がる）。

## 構築

```sh
createdb jammemo
psql -d jammemo -f ddl/users.sql
psql -d jammemo -f ddl/sessions.sql
```

## アカウントの作成

**新規登録の UI は無い。** アカウントは DB へ直接入れる。パスワードのハッシュは
`ddl/passwd.pl` が作る（パスワードは端末から聞くので、シェルの履歴や `ps` に残らない）。

```sh
./ddl/passwd.pl you@example.com yourname   # INSERT 文が出る
./ddl/passwd.pl you@example.com            # パスワード変更の UPDATE 文が出る
```

出力された SQL をそのまま流す。

```sh
./ddl/passwd.pl you@example.com yourname | psql -d jammemo
```

## アカウントの確認・削除

```sh
psql -d jammemo -c "SELECT id, username, email, created_at FROM users ORDER BY id"
psql -d jammemo -c "DELETE FROM users WHERE email = 'you@example.com'"
```

ユーザーを消すと、そのユーザーのセッションも `ON DELETE CASCADE` で消える
（＝ログイン中の端末はすぐ弾かれる）。全端末を強制ログアウトさせたいだけなら:

```sh
psql -d jammemo -c "DELETE FROM sessions"
```
