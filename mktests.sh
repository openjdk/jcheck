#! /bin/bash

export HGRCPATH=

rm -rf tests
hg init tests
cd tests

cat >.hg/hgrc <<___
[extensions]
fetch =
jcheck = $(pwd)/../jcheck.py
[hooks]
pretxnchangegroup = python:jcheck.hook
___

touch .jcheck

date >date
HGUSER=setup hg ci -Am '1000000: Init
Reviewed-by: duke'

echo 1000001 >.hg/bugid

bugid() {
  b=$(expr $(cat .hg/bugid) + 1)
  echo $b >.hg/bugid
  echo $b
}

datefile=date

test() {
  date >>$datefile; hg add --exclude 'z*'
  export HGUSER=$1; shift
  if [ -z "$*" ]; then
    msg="$(bugid): Bug
Reviewed-by: duke"
    (set -x; hg ci -m "$msg")
  else
    (set -x; hg "$@")
  fi
}

pass() { test pass "$@"; }
fail() { test fail "$@"; }
setup() { test setup "$@"; }


# Merge-changeset comments
# THESE MUST BE FIRST since they refer to specific revision indices

setup ci -m "$(bugid): Bug to merge
Reviewed-by: duke"
hg bundle --base 0 -r 1 z
hg rollback
(datefile=date2 setup ci -m "$(bugid): Merge to bug
Reviewed-by: duke")
(export HGUSER=fail; set -x; hg fetch z)
rm z

setup ci -m "$(bugid): Bug to merge
Reviewed-by: duke"
hg bundle --base 3 -r 4 z
hg rollback
(datefile=date3 setup ci -m "$(bugid): Merge to bug
Reviewed-by: duke")
(export HGUSER=pass; set -x; hg fetch -m Merge z)
rm z


# File content

echo 'alpha
beta
foo ' >trailing-space
fail

echo 'alpha
beta
foo' >carriage-return
fail

echo 'alpha
beta
foo	bar' >tab
fail


# File modes and types

touch executable
chmod +x executable
fail

ln -s foo symlink
fail


# Changeset comments

fail ci -m "Blah blah"

pass ci -m "$(bugid): A random bug
Reviewed-by: duke"

fail ci -m " $(bugid): A random bug
Reviewed-by: duke"

fail ci -m "$(bugid):
Reviewed-by: duke"

fail ci -m "Reviewed-by: duke"

fail ci -m "$(bugid): A random bug
Blah blah
Reviewed-by: duke"

fail ci -m "$(bugid): A random bug"

fail ci -m "$(bugid): A random bug
Reviewed-by:"

fail ci -m "$(bugid): A random bug
Blah blah"

fail ci -m "$(bugid): A random bug
Reviewed-by: foo@bar.baz"

fail ci -m "$(bugid): The next bug
Reviewed-by: Ben Bitdiddle"

pass ci -m "$(bugid): A random bug
$(bugid): Another random bug
Reviewed-by: duke"

fail ci -m "$(bugid): A random bug [foo.bar]
Reviewed-by: duke"

fail ci -m "123456: A short bugid
Reviewed-by: duke"

fail ci -m "nobugid: No bugid
Reviewed-by: duke"

pass ci -m "$(bugid): The next bug
Reviewed-by: mr, kgh"

fail ci -m "$(bugid): The next bug
Reviewed-by: mr kgh"

fail ci -m "$(bugid): Another bug
Contributed-by: Ben Bitdiddle <ben@bits.org>"

pass ci -m "$(bugid): Another bug
Reviewed-by: duke
Contributed-by: ben@bits.org"

pass ci -m "$(bugid): Another bug
Reviewed-by: duke
Contributed-by: Ben Bitdiddle <ben@bits.org>"

fail ci -m "$(bugid): Another bug
Reviewed-by: duke
Contributed-by: Ben Bitdiddle"

fail ci -m "$(bugid): Another bug
Reviewed-by: duke
Contributed-by: foo"

fail ci -m "$(bugid): Another bug
Reviewed-by:
Contributed-by: ben@bits.org"

pass ci -m "$(bugid): Yet another bug
Summary: Rewrite code
Reviewed-by: duke"

fail ci -m "$(bugid): Yet another bug
Summary: 
Reviewed-by: duke"

fail ci -m "$(bugid): Yet another bug
Summary: Rewrite code

Reviewed-by: duke"

fail ci -m "1000002: Duplicate bugid
Reviewed-by: duke"

b=$(bugid)
fail ci -m "$b: Duplicate bugid in changeset
$b: Duplicate bugid in changeset
Reviewed-by: duke"

# hg seems to strip trailing whitespace,
# at least for comments given with -m
pass ci -m "$(bugid): That's some bug 
Reviewed-by: duke"

pass ci -m "$(bugid): That's some bug
Reviewed-by: duke "

pass ci -m "$(bugid): That's some bug
Reviewed-by: duke"

fail ci -m "$(bugid): That's some	bug
Reviewed-by: duke"

fail ci -m "$(bugid): Buggy bug bug bug
Reviewed-by: fang"

test fang ci -m "$(bugid): Buggy bug bug bug
Reviewed-by: beelzebub"
