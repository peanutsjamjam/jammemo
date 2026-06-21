#!/usr/local/bin/perl
use strict;
use warnings;
use utf8;
use POSIX qw(strftime);
use JSON::PP;
use File::Glob qw(:bsd_glob);
use File::Basename qw(dirname basename);

# jam memo 保存API (CGI / Perl)
#
# メモは memo_data/ に「1メモ=1ファイル」で保存する。
#   - ファイル名: YYYY_MM_DD_NNNN.txt  (例: 2026_06_20_0001.txt)
#   - 中身      : 1行目=タイトル, 2行目=作成日時, 3行目=最終更新日時, 4行目以降=内容
#                 （作成/更新日時は epoch 秒。ファイル内に持つので OS 非依存）
#
# エンドポイント (REQUEST_METHOD で分岐):
#   GET                  -> 全メモを JSON 配列で返す [{id,title,content,created,updated}, ...]
#   GET    ?example=1    -> 設定プレビュー用サンプル {title,content} を返す
#   POST                 -> 新規の空メモを作成し {id,title,content,created,updated} を返す
#   PUT    ?id=<id>      -> 本文 {title,content} を保存し {ok,updated} を返す
#   DELETE ?id=<id>      -> 削除
#
# memo_data/example.txt は設定画面のフォントサイズ確認用サンプル。
# 無ければ自動生成する（ID 形式ではないので一覧には出ない）。

my $BASE_DIR = dirname(__FILE__);
my $DATA_DIR = "$BASE_DIR/memo_data";
my $ID_RE    = qr/^\d{4}_\d{2}_\d{2}_\d{4}$/;
my $JSON     = JSON::PP->new->utf8;

sub respond {
    my ($data, $status) = @_;
    $status ||= '200 OK';
    my $body = $JSON->encode($data);
    binmode STDOUT;
    print "Status: $status\r\n";
    print "Content-Type: application/json; charset=utf-8\r\n";
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
    my $raw = '';
    read(STDIN, $raw, $length);
    return {} if !defined $raw || $raw eq '';
    my $data = eval { $JSON->decode($raw) };
    return $data && ref($data) eq 'HASH' ? $data : {};
}

sub get_id {
    my $qs = $ENV{QUERY_STRING} || '';
    for my $pair (split /&/, $qs) {
        my ($k, $v) = split /=/, $pair, 2;
        next unless defined $k && $k eq 'id';
        $v = '' unless defined $v;
        $v =~ tr/+/ /;
        $v =~ s/%([0-9A-Fa-f]{2})/chr(hex($1))/ge;
        return $v;
    }
    return undef;
}

my $method = uc($ENV{REQUEST_METHOD} || 'GET');

eval {
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
    fail("server error: $err", "500 Internal Server Error");
};
