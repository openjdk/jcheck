#! /bin/bash

export HGRCPATH=

# No insult intended here -- we just need valid author names for the tests
pass_author=ohair
fail_author=mr
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
  case $au in
    $pass_author) type=pass;;
    $fail_author) type=fail;;
    $setup_author) type=setup;;
    *) type=$au;;
  esac
  echo "-- $r $type"
  if [ $type = setup ]; then
    r=$(expr $r + 1)
    continue
  fi
  hg jcheck -r $r "$@"
  rv=$?
  case $type in
    pass) if [ $rv != 0 ]; then fail $r; fi;;
    fail|fang) if [ $rv == 0 ]; then fail $r; fi;;
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
HG='hg --config hooks.pretxnchangegroup=python:jcheck.strict_hook'
if HGUSER=$setup_author $HG pull z; then fail $r; fi
hg revert date.$n.2
rm -rf z
r=$(expr $r + 1)

# Named branches

echo "-- $r named branches"
hg branch foo
date >date.$r
hg add date.$r
HG='hg --config hooks.pretxncommit=python:jcheck.hook'
if HGUSER=$setup_author $HG ci -m "$(bugid): Branch
Reviewed-by: duke" ; then fail $r; fi
hg rollback; hg revert -a
rm .hg/branch ## hg bug ?
r=$(expr $r + 1)

# Tags

HG='hg --config hooks.pretxncommit=python:jcheck.hook'
for t in foo jdk7 jdk7-b1; do
  echo "-- $r tag $t"
  if HGUSER=$setup_author $HG tag -r 1 $t; then hg rollback; fail $r; fi
  hg revert -a; rm .hgtags
  r=$(expr $r + 1)
done

HG='hg --config hooks.pretxncommit=python:jcheck.hook'
for t in jdk7-b01 jdk7-b123; do
  echo "-- $r tag $t"
  if ! HGUSER=$setup_author $HG tag -r 1 $t; then fail $r; fi
  hg rollback; hg revert -a; rm .hgtags
  r=$(expr $r + 1)
done


# Summary

if [ $failures -gt 0 ]; then
  echo "-- FAILURES: $failures"
else
  echo "-- All tests passed"
fi
[ $failures != 0 ] && exit 1 || exit 0
