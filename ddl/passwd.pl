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
use File::Basename qw(dirname);

# パスワードのハッシュは api.cgi と同じ実装でなければならないので、共通ライブラリ
# PJJ::Crypt を使う（api.cgi の1つ上のディレクトリの env.pl が置き場所を教える）。
our $PJJ_LIB;
BEGIN {
    require Cwd;   # require は相対パスだと @INC を探すので絶対パスにする
    my $env_file = Cwd::abs_path(dirname(__FILE__) . '/..') . '/env.pl';
    require $env_file if -f $env_file;
    my ($lib) = grep { defined && length && -d } (
        $ENV{PJJ_LIB}, $PJJ_LIB, '/var/lib/perl5', '/home/sugawara/lib/perl5');
    die "PJJ library not found\n" unless $lib;
    unshift @INC, $lib;
}
use PJJ::Crypt qw(random_hex pbkdf2);

my $ITER = 120000;   # api.cgi の $PBKDF2_ITER と揃えること

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
