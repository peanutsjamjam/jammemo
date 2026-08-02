#!/usr/bin/perl
# DBI 入りのシステム perl を使う（/usr/local/bin/perl には DBD::Pg が無い）。
use strict;
use warnings;
use utf8;
use POSIX qw(strftime);
use JSON::PP;
use DBI;
use Digest::SHA qw(hmac_sha256);
use File::Glob qw(:bsd_glob);
use File::Basename qw(dirname basename);

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
my $DB_NAME      = 'jammemo';
my $COOKIE_NAME  = 'jammemo_sid';
my $SESSION_DAYS = 30;
my $PBKDF2_ITER  = 120000;   # ddl/passwd.pl と揃えること
# リクエストボディの上限。メモ本文しか送らないので控えめでよい。
my $MAX_BODY_BYTES = 1024 * 1024;

# Cookie の Path は配信 URL のディレクトリ（例 /~sugawara/jammemo/）に合わせる。
my $COOKIE_PATH = $ENV{SCRIPT_NAME} || '/';
$COOKIE_PATH =~ s#/[^/]*$#/#;
$COOKIE_PATH = '/' if $COOKIE_PATH eq '';

# Set-Cookie など、respond のときに一緒に出すヘッダ。
my @EXTRA_HEADERS;
sub add_header { push @EXTRA_HEADERS, $_[0]; }

sub respond {
    my ($data, $status) = @_;
    $status ||= '200 OK';
    my $body = $JSON->encode($data);
    binmode STDOUT;
    print "Status: $status\r\n";
    print "Content-Type: application/json; charset=utf-8\r\n";
    print "$_\r\n" for @EXTRA_HEADERS;
    print "Content-Length: " . length($body) . "\r\n";
    print "\r\n";
    print $body;
    exit 0;
}

sub fail {
    my ($message, $status) = @_;
    $status ||= '400 Bad Request';
    respond({ error => $message }, $status);
}

# ---- 認証 ------------------------------------------------------------------
sub db {
    my $dbh = DBI->connect(
        "dbi:Pg:dbname=$DB_NAME", '', '',
        { RaiseError => 1, AutoCommit => 1, PrintError => 0, pg_enable_utf8 => 1 }
    ) or fail('db_error', '500 Internal Server Error');
    return $dbh;
}

sub random_hex {
    my ($bytes) = @_;
    open my $fh, '<:raw', '/dev/urandom' or die "urandom: $!";
    read($fh, my $buf, $bytes);
    close $fh;
    return unpack('H*', $buf);
}

# PBKDF2-HMAC-SHA256（dkLen = 1ブロック）。ddl/passwd.pl と同じ実装にすること。
sub pbkdf2 {
    my ($password, $salt_hex, $iter) = @_;
    my $salt = pack('H*', $salt_hex);
    utf8::encode($password) if utf8::is_utf8($password);
    my $u   = hmac_sha256($salt . pack('N', 1), $password);
    my $out = $u;
    for (my $i = 1; $i < $iter; $i++) {
        $u = hmac_sha256($u, $password);
        $out ^= $u;
    }
    return unpack('H*', $out);
}

# ハッシュの比較は、一致した文字数から情報が漏れないよう定数時間で行う。
sub const_eq {
    my ($x, $y) = @_;
    return 0 if length($x) != length($y);
    my $r = 0;
    $r |= ord(substr($x, $_, 1)) ^ ord(substr($y, $_, 1)) for 0 .. length($x) - 1;
    return $r == 0;
}

sub get_cookie {
    my ($name) = @_;
    my $raw = $ENV{HTTP_COOKIE} || '';
    for my $pair (split /;\s*/, $raw) {
        my ($k, $v) = split /=/, $pair, 2;
        next unless defined $k && $k eq $name;
        return defined $v ? $v : '';
    }
    return undef;
}

sub set_session_cookie {
    my ($token) = @_;
    my $max = $SESSION_DAYS * 24 * 3600;
    add_header("Set-Cookie: $COOKIE_NAME=$token; Path=$COOKIE_PATH; Max-Age=$max; HttpOnly; Secure; SameSite=Lax");
}

sub clear_session_cookie {
    add_header("Set-Cookie: $COOKIE_NAME=; Path=$COOKIE_PATH; Max-Age=0; HttpOnly; Secure; SameSite=Lax");
}

sub purge_expired_sessions {
    my ($dbh) = @_;
    eval { $dbh->do('DELETE FROM sessions WHERE expires_at < now()'); 1 }
        or warn "purge_expired_sessions failed: $@\n";
}

sub start_session {
    my ($dbh, $uid) = @_;
    my $token = random_hex(32);
    $dbh->do(
        "INSERT INTO sessions (token, user_id, expires_at)
         VALUES (?,?, now() + interval '$SESSION_DAYS days')",
        undef, $token, $uid
    );
    purge_expired_sessions($dbh);
    set_session_cookie($token);
}

# 現在のログインユーザー {id, username, email}。未ログインなら undef。
sub current_user {
    my ($dbh) = @_;
    my $token = get_cookie($COOKIE_NAME);
    return undef unless defined $token && $token =~ /^[0-9a-f]{16,128}$/;
    return $dbh->selectrow_hashref(
        'SELECT u.id, u.username, u.email FROM sessions s
           JOIN users u ON u.id = s.user_id
          WHERE s.token = ? AND s.expires_at > now()',
        undef, $token
    );
}

sub require_user {
    my ($dbh) = @_;
    my $u = current_user($dbh);
    fail('not_authenticated', '401 Unauthorized') unless $u;
    return $u;
}

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

sub read_body_json {
    my $length = $ENV{CONTENT_LENGTH} || 0;
    return {} if $length <= 0;
    # 読み込む前に上限で弾く（CONTENT_LENGTH を鵜呑みにしてメモリを食い潰さない）。
    fail("payload too large", "413 Payload Too Large") if $length > $MAX_BODY_BYTES;
    my $raw = '';
    read(STDIN, $raw, $length);
    return {} if !defined $raw || $raw eq '';
    my $data = eval { $JSON->decode($raw) };
    return $data && ref($data) eq 'HASH' ? $data : {};
}

sub query_param {
    my ($name) = @_;
    my $qs = $ENV{QUERY_STRING} || '';
    for my $pair (split /&/, $qs) {
        my ($k, $v) = split /=/, $pair, 2;
        next unless defined $k && $k eq $name;
        $v = '' unless defined $v;
        $v =~ tr/+/ /;
        $v =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/ge;
        return $v;
    }
    return undef;
}

sub get_id { return query_param('id'); }

my $method = uc($ENV{REQUEST_METHOD} || 'GET');
my $action = query_param('action') || '';

eval {
    my $dbh = db();

    # ---- 認証系（ログイン前でも叩ける） ----
    if ($action eq 'login' && $method eq 'POST') {
        my $body     = read_body_json();
        my $email    = defined $body->{email}    ? $body->{email}    : '';
        my $password = defined $body->{password} ? $body->{password} : '';
        $email =~ s/^\s+|\s+$//g;

        my $u = $dbh->selectrow_hashref(
            'SELECT id, username, email, password_hash, salt, iterations
               FROM users WHERE lower(email) = lower(?)',
            undef, $email
        );
        # ユーザーが居なくてもダミーで PBKDF2 を回す。応答時間の差から
        # 「そのメールが登録済みか」が分かってしまうのを防ぐため。
        my $ok = 0;
        if ($u) {
            my $hash = pbkdf2($password, $u->{salt}, $u->{iterations});
            $ok = const_eq($hash, $u->{password_hash});
        } else {
            pbkdf2($password, '0' x 32, $PBKDF2_ITER);
        }
        fail('invalid_credentials', '401 Unauthorized') unless $ok;

        start_session($dbh, $u->{id});
        respond({ username => $u->{username}, email => $u->{email} });
    }
    elsif ($action eq 'logout' && $method eq 'POST') {
        my $token = get_cookie($COOKIE_NAME);
        $dbh->do('DELETE FROM sessions WHERE token = ?', undef, $token)
            if defined $token && $token =~ /^[0-9a-f]{16,128}$/;
        clear_session_cookie();
        respond({ ok => JSON::PP::true });
    }
    elsif ($action eq 'me' && $method eq 'GET') {
        my $u = require_user($dbh);
        respond({ username => $u->{username}, email => $u->{email} });
    }

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
