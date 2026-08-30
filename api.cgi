#!/usr/bin/perl
# DBI/DBD::Pg の入ったシステムの perl（/usr/bin/perl）で動かす。DB 接続は PJJ::DB 経由。
use strict;
use warnings;
use utf8;
use POSIX qw(strftime);
use JSON::PP;
use File::Glob qw(:bsd_glob);
use File::Basename qw(dirname basename);

# 共通ライブラリ PJJ（サインイン／セッションの土台。github.com/peanutsjamjam/pjj-perl5）を
# @INC に足す。use はコンパイル時に解決されるので、env.pl の読み込みごと BEGIN の中で行う。
# 探索順は $ENV{PJJ_LIB}（テスト用）→ $main::PJJ_LIB（env.pl）→ 本番 → dev。
our $PJJ_LIB;   # env.pl が設定する（未設定なら下のフォールバックを使う）
BEGIN {
    require Cwd;   # require は相対パスだと @INC を探すので絶対パスにする
    my $env_file = Cwd::abs_path(dirname(__FILE__)) . '/env.pl';
    require $env_file if -f $env_file;
    my ($lib) = grep { defined && length && -d } (
        $ENV{PJJ_LIB}, $PJJ_LIB, '/var/lib/perl5', '/home/sugawara/lib/perl5');
    die "PJJ library not found\n" unless $lib;
    unshift @INC, $lib;
}
use PJJ;
use PJJ::Web;
use PJJ::DB;
use PJJ::Session;
use PJJ::Auth;

# jam memo 保存API (CGI / Perl)
#
# メモは memo_data/ に「1メモ=1ファイル」で保存する。
#   - ファイル名: YYYY_MM_DD_NNNN.txt  (例: 2026_06_20_0001.txt)
#   - 中身      : 1行目=タイトル, 2行目=作成日時, 3行目=最終更新日時, 4行目以降=内容
#                 （作成/更新日時は epoch 秒。ファイル内に持つので OS 非依存）
#
# ログイン: メモの読み書きにはログインが必要。ユーザー情報は PostgreSQL の
#   jammemo データベース（users / sessions）に置く。新規登録の UI は無く、
#   アカウントは DB へ直接入れる（ddl/README.md 参照）。
#   セッションは Cookie jammemo_sid（HttpOnly / Secure / SameSite=Lax）で受け渡す。
#
# エンドポイント (?action= と REQUEST_METHOD で分岐):
#   POST   ?action=login   -> {email,password} で認証し {username,email} を返す
#   POST   ?action=logout  -> セッションを破棄する
#   GET    ?action=me      -> {username,email}。未ログインなら 401
#   GET                  -> 全メモを JSON 配列で返す [{id,title,content,created,updated}, ...]
#   GET    ?example=1    -> 設定プレビュー用サンプル {title,content} を返す
#   POST                 -> 新規の空メモを作成し {id,title,content,created,updated} を返す
#   PUT    ?id=<id>      -> 本文 {title,content} を保存し {ok,updated} を返す
#   DELETE ?id=<id>      -> 削除
#   （メモ系はすべて要ログイン。未ログインは 401 {error:"not_authenticated"}）
#
# memo_data/example.txt は設定画面のフォントサイズ確認用サンプル。
# 無ければ自動生成する（ID 形式ではないので一覧には出ない）。

my $BASE_DIR = dirname(__FILE__);
my $DATA_DIR = "$BASE_DIR/memo_data";
my $ID_RE    = qr/^\d{4}_\d{2}_\d{2}_\d{4}$/;
my $JSON     = JSON::PP->new->utf8;

# ---- 認証まわりの設定 ------------------------------------------------------
my $COOKIE_NAME  = 'jammemo_sid';
my $SESSION_DAYS = 30;
my $PBKDF2_ITER  = 120000;   # ddl/passwd.pl と揃えること
# リクエストボディの上限。メモ本文しか送らないので控えめでよい。
my $MAX_BODY_BYTES = 1024 * 1024;

# 接続する PostgreSQL のデータベース名。env.pl（git 管理外）で上書きできる。
# env.pl はファイル冒頭の BEGIN で読み込み済みなので、未設定のときだけ既定値を入れる。
our $JAMMEMO_DB;
$JAMMEMO_DB = 'jammemo' unless defined $JAMMEMO_DB && length $JAMMEMO_DB;

# 共通ライブラリ PJJ の設定。このアプリと他アプリの違いは、すべてここで吸収する。
# Cookie の Path（配信 URL のディレクトリ。例 /~sugawara/jammemo/）は
# PJJ が SCRIPT_NAME から自動判定する。
PJJ->init(
    app            => 'jam memo',
    db             => $JAMMEMO_DB,
    cookie_name    => $COOKIE_NAME,
    session_days   => $SESSION_DAYS,
    pbkdf2_iter    => $PBKDF2_ITER,
    max_body_bytes => $MAX_BODY_BYTES,
    # 新規登録・パスワード再設定の UI が無いアプリなので、認証は3つだけ受け付ける
    # （アカウントは ddl/passwd.pl が作る SQL を DB へ直接入れる）。
    auth_actions   => [qw(login logout me)],
);

# ---- メモの読み書き --------------------------------------------------------
sub ensure_data_dir {
    mkdir $DATA_DIR unless -d $DATA_DIR;
}

sub memo_path {
    my ($id) = @_;
    return "$DATA_DIR/$id.txt";
}

sub to_epoch {
    my ($v) = @_;
    return (defined $v && $v =~ /^\d+$/) ? 0 + $v : undef;
}

sub read_memo {
    my ($id) = @_;
    open my $fh, '<:encoding(UTF-8)', memo_path($id) or return undef;
    local $/;
    my $raw = <$fh>;
    close $fh;
    $raw = '' unless defined $raw;
    # 1行目=タイトル, 2行目=作成, 3行目=更新, 4行目以降=内容
    my ($title, $created, $updated, $content) = split /\n/, $raw, 4;
    $title   = '' unless defined $title;
    $content = '' unless defined $content;
    return {
        id      => $id,
        title   => $title,
        content => $content,
        created => to_epoch($created),
        updated => to_epoch($updated),
    };
}

sub write_memo {
    my ($id, $title, $content, $created, $updated) = @_;
    # タイトルは1行に矯正（改行を除去）
    $title =~ s/\r//g;
    $title =~ s/\n/ /g;
    # 改行コードを LF に正規化
    $content =~ s/\r\n/\n/g;
    $content =~ s/\r/\n/g;
    ensure_data_dir();
    open my $fh, '>:encoding(UTF-8)', memo_path($id) or fail("write failed", "500 Internal Server Error");
    # 1行目=タイトル, 2行目=作成, 3行目=更新, 4行目以降=内容
    print $fh "$title\n$created\n$updated\n$content";
    close $fh;
}

sub example_path {
    return "$DATA_DIR/example.txt";
}

# 設定プレビュー用サンプルが無ければ作成する
sub ensure_example {
    ensure_data_dir();
    my $path = example_path();
    return if -e $path;
    open my $fh, '>:encoding(UTF-8)', $path or return;
    print $fh "ヘルシー豚バラ炒め\n豚バラ肉 200g\nトマト 1個\nにら 1/2束\nにんにく 1かけ";
    close $fh;
}

sub read_example {
    ensure_example();
    open my $fh, '<:encoding(UTF-8)', example_path()
        or return { title => '', content => '' };
    local $/;
    my $raw = <$fh>;
    close $fh;
    $raw = '' unless defined $raw;
    my ($title, $content) = split /\n/, $raw, 2;
    $title   = '' unless defined $title;
    $content = '' unless defined $content;
    # ファイルの更新時刻をサンプルの作成/更新日時として返す
    my $mtime = (stat example_path())[9] || time;
    return {
        title   => $title,
        content => $content,
        created => $mtime,
        updated => $mtime,
    };
}

sub list_memos {
    ensure_data_dir();
    my @memos;
    for my $path (sort glob("$DATA_DIR/*.txt")) {
        my $id = basename($path);
        $id =~ s/\.txt$//;
        next unless $id =~ $ID_RE;
        my $memo = read_memo($id);
        push @memos, $memo if $memo;
    }
    return \@memos;
}

sub next_id {
    ensure_data_dir();
    my $date    = strftime('%Y_%m_%d', localtime);
    my $max_seq = 0;
    for my $path (glob("$DATA_DIR/${date}_*.txt")) {
        if ($path =~ /_(\d{4})\.txt$/) {
            $max_seq = $1 if $1 > $max_seq;
        }
    }
    return sprintf('%s_%04d', $date, $max_seq + 1);
}

sub get_id { return query_param('id'); }

my $method = uc($ENV{REQUEST_METHOD} || 'GET');
my $action = query_param('action') || '';

eval {
    my $dbh = db();

    # 認証系（ログイン前でも叩ける）は PJJ::Auth が処理する。このアプリは新規登録の UI が
    # 無いので、受け付けるのは login / logout / me だけ（auth_actions で絞ってある）。
    auth_dispatch($dbh, $action, $method);

    # ---- メモ系（ここから先はすべて要ログイン） ----
    require_user($dbh);

    if ($method eq 'GET') {
        my $qs = $ENV{QUERY_STRING} || '';
        respond(read_example()) if $qs =~ /(?:^|&)example(?:=|&|$)/;
        ensure_example();
        respond(list_memos());
    }
    elsif ($method eq 'POST') {
        my $id  = next_id();
        my $now = time();
        write_memo($id, '', '', $now, $now);
        respond(read_memo($id));
    }
    elsif ($method eq 'PUT') {
        my $id = get_id();
        fail("invalid id") unless defined $id && $id =~ $ID_RE;
        fail("not found", "404 Not Found") unless -e memo_path($id);
        my $body = read_body_json();
        # 作成日時は既存値を引き継ぐ（無ければ今）
        my $existing = read_memo($id);
        my $now      = time();
        my $created  = ($existing && defined $existing->{created}) ? $existing->{created} : $now;
        write_memo($id, $body->{title} // '', $body->{content} // '', $created, $now);
        respond({ ok => JSON::PP::true, updated => $now });
    }
    elsif ($method eq 'DELETE') {
        my $id = get_id();
        fail("invalid id") unless defined $id && $id =~ $ID_RE;
        unlink memo_path($id) if -e memo_path($id);
        respond({ ok => JSON::PP::true });
    }
    else {
        fail("method not allowed", "405 Method Not Allowed");
    }
    1;
} or do {
    my $err = $@ || 'unknown error';
    # 詳細（ファイルパス・行番号を含む）はサーバーログへ。クライアントには汎用メッセージだけ返す。
    warn "jammemo api error: $err\n";
    fail("server error", "500 Internal Server Error");
};
