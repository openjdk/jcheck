#! /bin/bash

export HGRCPATH=
hg version | head -1

# No insult intended here -- we just need valid author names for the tests
pass_author=ohair
pass_author_lax=andrew
fail_author=mr
fail_author_lax=robilad
setup_author=xdono

cd $(dirname $0)/tests

last=$(hg tip --template '{rev}')

failures=0

fail() {
  echo "-- $r: TEST FAILED"
  failures=$(expr $failures + 1)
  if [ $FAILFIRST ]; then exit 2; fi
}

# Cases created by mktests

r=0
while [ $r -le $last ]; do
  au=$(hg log -r $r --template '{author}')
  lax=
  case $au in
    $pass_author) type=pass;;
    $pass_author_lax) type=pass; lax='--lax';;
    $fail_author) type=fail;;
    $fail_author_lax) type=fail; lax='--lax';;
    $setup_author) type=setup;;
    *) type=$au;;
  esac
  echo "-- $r $type"
  if [ $type = setup ]; then
    r=$(expr $r + 1)
    continue
  fi
  hg jcheck $lax -r $r "$@"
  rv=$?
  case $type in
    pass) if [ $rv != 0 ]; then fail $r; fi;;
    fail|fang) if [ $rv = 0 ]; then fail $r; fi;;
  esac
  r=$(expr $r + 1)
done

# Cases that require richer logic

echo 9000000 >.hg/bugid

bugid() {
  b=$(expr $(cat .hg/bugid) + 1)
  echo $b >.hg/bugid
  echo $b
}

# pretxnchangegroup hook

echo "-- $r pretxnchangegroup"
rm -rf z
hg init z
mkdir z/.jcheck
echo 'project=jdk7' >z/.jcheck/conf
cp .hg/hgrc z/.hg
if hg push z; then fail; fi
r=$(expr $r + 1)

# Multiple heads

echo "-- $r multiple heads"
n=$(hg id -n)
date >>date.$n
hg add date.$n
HGUSER=$setup_author hg ci -m "$(bugid): Head one
Reviewed-by: duke"
rm -rf z
hg bundle --base $n -r $(expr $n + 1) z
hg rollback
hg revert date.$n
date >>date.$n.2
hg add date.$n.2
HGUSER=$setup_author hg ci -m "$(bugid): Head two
Reviewed-by: duke"
HG='hg --config hooks.pretxnchangegroup.jcheck=python:jcheck.strict_hook'
if HGUSER=$setup_author $HG pull z; then fail $r; fi
hg revert date.$n.2
rm -rf z
r=$(expr $r + 1)

# Named branches

echo "-- $r named branches"
hg branch foo
date >date.$r
hg add date.$r
HG='hg --config hooks.pretxncommit.jcheck=python:jcheck.hook'
if HGUSER=$setup_author $HG ci -m "$(bugid): Branch
Reviewed-by: duke" ; then fail $r; fi
hg rollback; hg revert -a
rm .hg/branch ## hg bug ?
r=$(expr $r + 1)

# Tags

# hg 1.6 and later strip whitespace from tag names (hg issue1217), so test a
# tag with trailing whitespace only in earlier versions.
whitespace_tag='jdk7-b01 '
hg -q version | python -c '
import sys, re;
m = re.search("version ([0-9]+)\.([0-9]+)", sys.stdin.readline())
if m:
    major = int(m.group(1))
    minor = int(m.group(2))
    if major == 1 and minor > 5 or major > 1:
       sys.exit(0) # version >= 1.6
sys.exit(1)'
[ $? -eq 0 ] && whitespace_tag=jdk7-b2 # a tag that should be rejected

# Bad tags
HG='hg --config hooks.pretxncommit.jcheck=python:jcheck.hook'
for t in foo tiptoe jdk7 jdk7-b1 "$whitespace_tag" \
         hs1-b02 hs11-b3 hs12-b004 hs13.001-b05 \
         jdk- jdk-9u1 jdk-9-1 jdk-9.01 \
         jdk8u8-GA jdk-9+100-gav hs13.10-b12-g \
         jdk8u8-b08-ga jdk-10.0.2+2-ga \
        jdk6u22 jdk6u-b01 jdk6u11-b1 jdk6u1000-b01 ; do
  echo "-- $r tag $t"
  if HGUSER=$setup_author $HG tag -r 1 "$t"; then hg rollback; fail $r; fi
  hg revert -a; rm .hgtags
  r=$(expr $r + 1)
done

# Good tags
HG='hg --config hooks.pretxncommit.jcheck=python:jcheck.hook'
for t in jdk4-b01 jdk5-b01 jdk6-b01 jdk7-b01 jdk8-b01 jdk9-b01 \
        jdk-9+1 jdk-10+1 \
        jdk4-b100 jdk8-b800 \
        jdk4u4-b04 jdk5u5-b05 jdk6u6-b06 jdk7u7-b07 jdk8u8-b08 jdk9u9-b09 \
        jdk8u80-b08 jdk8u100-b100 \
        jdk-9+100 jdk-9.1.2.1+3 jdk-9.0.1+42 jdk-9.0.1.19+43 \
        jdk-9-ga jdk-11.0.2-ga jdk8u192-ga \
        hs11-b02 hs12.1-b11 hs13.10-b12 ; do
  echo "-- $r tag $t"
  if ! HGUSER=$setup_author $HG tag -r 1 "$t"; then fail $r; fi
  hg rollback; hg revert -a; rm .hgtags
  r=$(expr $r + 1)
done

# Black/white lists

blackhash=b5dd894e33c0dfa6cde0c5c5fd1f7a7e5edd6f01
whitehash=1c3c89ae5adcd57d074a268c5328df476ccabf52
rm -rf z
hg init z
mkdir z/.jcheck
echo 'project=jdk7' >z/.jcheck/conf

cat >z/.hg/hgrc <<___
[extensions]
jcheck_test = $(pwd)/jcheck_test.py
___

echo "-- $r blacklist"
echo foo >z/foo
hg add -R z z/foo
HGUSER=$setup_author hg ci -R z -m '1010101: Good but black
Reviewed-by: duke' -d '0 0'
if hg jcheck_test --black $blackhash -R z -r tip; then fail; fi
r=$(expr $r + 1)

echo "-- $r blacklist file 1"
echo "$blackhash # blacklisted" > blacklist
if hg jcheck_test -R z -r tip; then fail; fi
rm -f blacklist
r=$(expr $r + 1)

echo "-- $r blacklist file 2"
echo "	$blackhash#" > blacklist
if hg jcheck_test -R z -r tip; then fail; fi
rm -f blacklist
r=$(expr $r + 1)

echo "-- $r blacklist file 3"
echo "#	$blackhash # not really blacklisted" > blacklist
if hg jcheck_test -R z -r tip; then true; else fail; fi
rm -f blacklist
r=$(expr $r + 1)

echo "-- $r whitelist"
echo foobar >z/foo
HGUSER=$setup_author hg ci -R z -m '1010101: Bad but white' -d '0 0'
if hg jcheck_test --white $whitehash -R z -r tip; then true; else fail; fi
r=$(expr $r + 1)

# Duplicate bugids
echo "-- $r duplicate bug ids"
rm -rf z
hg init z
mkdir z/.jcheck
cat >z/.jcheck/conf <<___
project=jdk7
comments=lax
bugids=dup
___
hg add -R z z/.jcheck/conf

HGUSER=$setup_author hg ci -R z -m '1111111: Foo!' -d '0 0'
touch z/foo
hg add -R z z/foo
if HGUSER=$setup_author hg ci -R z -m '1111111: Foo!'; then true; else fail; fi
r=$(expr $r + 1)

# Lax bugids
echo "-- $r lax bug ids"
rm -rf z
hg init z
mkdir z/.jcheck
cat >z/.jcheck/conf <<___
project=jdk7
comments=lax
bugids=lax
___
hg add -R z z/.jcheck/conf

if HGUSER=$setup_author hg ci -R z -m '1234: Silly bugid'; then true; else fail; fi
r=$(expr $r + 1)

# Ignore bugids
echo "-- $r ignore bug ids 1"
rm -rf z
hg init z
cat >z/.hg/hgrc <<___
[extensions]
jcheck = $(pwd)/jcheck.py
[hooks]
pretxncommit.jcheck=python:jcheck.hook
___
mkdir z/.jcheck
cat >z/.jcheck/conf <<___
project=jdk7
bugids=ignore
___
hg add -R z z/.jcheck/conf

if HGUSER=$setup_author hg ci -R z -m "OPENJDK6-1: test separate bugids
Reviewed-by: $pass_author"; then true; else fail; fi
r=$(expr $r + 1)

echo "-- $r ignore bug ids 2"
rm -rf z
hg init z
cat >z/.hg/hgrc <<___
[extensions]
jcheck = $(pwd)/jcheck.py
[hooks]
pretxncommit.jcheck=python:jcheck.hook
___
mkdir z/.jcheck
cat >z/.jcheck/conf <<___
project=jdk7
bugids=ignore
___
hg add -R z z/.jcheck/conf

if HGUSER=$setup_author hg ci -R z -m "openjdk6-2: test separate bugids
Reviewed-by: $pass_author"; then fail; else true; fi
r=$(expr $r + 1)

echo "-- $r ignore bug ids 3"
rm -rf z
hg init z
cat >z/.hg/hgrc <<___
[extensions]
jcheck = $(pwd)/jcheck.py
[hooks]
pretxncommit.jcheck=python:jcheck.hook
___
mkdir z/.jcheck
cat >z/.jcheck/conf <<___
project=jdk7
bugids=ignore
___
hg add -R z z/.jcheck/conf

if HGUSER=$setup_author hg ci -R z -m "6-2: test separate bugids
Reviewed-by: $pass_author"; then fail; else true; fi

echo "-- $r ignore bug ids 4"
rm -rf z
hg init z
cat >z/.hg/hgrc <<___
[extensions]
jcheck = $(pwd)/jcheck.py
[hooks]
pretxncommit.jcheck=python:jcheck.hook
___
mkdir z/.jcheck
cat >z/.jcheck/conf <<___
project=jdk7
bugids=dup
___
hg add -R z z/.jcheck/conf

if HGUSER=$setup_author hg ci -R z -m "OPENJDK-42: Don't collect non-numeric bugids
Reviewed-by: $pass_author" >z/log 2>&1; then fail; else
  if grep 'ValueError' z/log; then fail; fi
fi
r=$(expr $r + 1)

# tags=lax tests
echo "-- $r tags=lax tag check"
rm -rf z
hg init z
mkdir z/.jcheck
cat >z/.jcheck/conf <<___
project=jdk7
tags=lax
___
hg add -R z z/.jcheck/conf
cat >z/.hg/hgrc <<___
[extensions]
jcheck = $(pwd)/jcheck.py
[hooks]
pretxncommit.jcheck=python:jcheck.hook
___
if HGUSER=$setup_author hg ci -R z -m '1111111: Foo!
Reviewed-by: duke' -d '0 0' \
   && HGUSER=$setup_author $HG tag -R z -r tip hsparent
then true; else fail; fi
r=$(expr $r + 1)

echo "-- $r tags=lax comment check"
touch z/foo
hg add -R z z/foo
HGUSER=$setup_author $HG ci -R z -m "Buggy bug bug bug
Reviewed-by: fang"
if [ $? -eq 0 ]; then fail; fi
r=$(expr $r + 1)

# Summary

if [ $failures -gt 0 ]; then
  echo "-- FAILURES: $failures"
else
  echo "-- All tests passed"
fi
[ $failures != 0 ] && exit 1 || exit 0
