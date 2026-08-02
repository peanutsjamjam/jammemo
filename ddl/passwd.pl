#!/usr/bin/perl
# アカウント作成・パスワード変更用の SQL を作るヘルパ。
# jam memo には新規登録の UI が無いので、アカウントは DB へ直接入れる。
#
#   ./ddl/passwd.pl <email> <username>        -> INSERT 文を出す（新規作成）
#   ./ddl/passwd.pl <email>                   -> UPDATE 文を出す（パスワード変更）
#
# パスワードは端末から聞く（コマンドライン引数にしないのは、シェルの履歴と
# ps の出力に残さないため）。出力された SQL を psql -d jammemo に流す。

use strict;
use warnings;
use Digest::SHA qw(hmac_sha256);

my $ITER = 120000;   # api.cgi の $PBKDF2_ITER と揃えること

sub random_hex {
    my ($bytes) = @_;
    open my $fh, '<:raw', '/dev/urandom' or die "urandom: $!";
    read($fh, my $buf, $bytes);
    close $fh;
    return unpack('H*', $buf);
}

# api.cgi の pbkdf2() と同じ実装（dkLen = ハッシュ長1ブロックぶん）。
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

sub quote_sql {
    my ($s) = @_;
    $s =~ s/'/''/g;
    return "'$s'";
}

sub prompt_password {
    # 端末から読むときだけエコーを止める（パイプ入力でも使えるようにしておく）。
    my $tty = -t STDIN;
    if ($tty) {
        print STDERR "パスワード: ";
        system('stty -echo');
    }
    my $pw = <STDIN>;
    if ($tty) {
        system('stty echo');
        print STDERR "\n";
    }
    die "パスワードが空です\n" unless defined $pw;
    chomp $pw;
    die "パスワードが空です\n" if $pw eq '';
    die "パスワードは8文字以上にしてください\n" if length($pw) < 8;
    return $pw;
}

my ($email, $username) = @ARGV;
unless (defined $email && $email ne '') {
    die "使い方: $0 <email> [username]\n"
      . "  username あり: 新規作成の INSERT を出す\n"
      . "  username なし: パスワード変更の UPDATE を出す\n";
}

my $password = prompt_password();
my $salt     = random_hex(16);
my $hash     = pbkdf2($password, $salt, $ITER);

if (defined $username && $username ne '') {
    printf "INSERT INTO users (username, email, password_hash, salt, iterations)\n"
         . "VALUES (%s, %s, %s, %s, %d);\n",
        quote_sql($username), quote_sql($email), quote_sql($hash), quote_sql($salt), $ITER;
} else {
    printf "UPDATE users SET password_hash = %s, salt = %s, iterations = %d\n"
         . " WHERE lower(email) = lower(%s);\n",
        quote_sql($hash), quote_sql($salt), $ITER, quote_sql($email);
}
