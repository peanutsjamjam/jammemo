-- users: アカウント。パスワードは PBKDF2-HMAC-SHA256 のハッシュで保存する。
--   jam memo には新規登録の UI が無い。アカウントは DB へ直接 INSERT/UPDATE して作る
--   （手順は ddl/README.md、ハッシュ生成は ddl/passwd.pl を使う）。
--   email はログイン ID。大文字小文字を無視して一意。
--   username は画面に出す表示名。
CREATE TABLE users (
  id            SERIAL PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  email         TEXT NOT NULL,
  password_hash TEXT NOT NULL,           -- PBKDF2-HMAC-SHA256 (hex)
  salt          TEXT NOT NULL,           -- hex
  iterations    INTEGER NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- メールアドレスは大文字小文字を無視して一意。
CREATE UNIQUE INDEX users_email_lower_uniq ON users (lower(email));
