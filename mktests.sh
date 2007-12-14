#! /bin/bash

rm -rf tests
hg init tests
cd tests

date >date
HGUSER=setup hg ci -Am '1000000: Init
Reviewed-by: duke'

echo 1000001 >.hg/bugid

bugid() {
  b=$(expr $(cat .hg/bugid) + 1)
  echo $b >.hg/bugid
  echo $b
}

test() {
  date >>date; hg add
  export HGUSER=$1; shift
  (set -x; hg "$@")
}

pass() { test pass "$@"; }
fail() { test fail "$@"; }
setup() { test setup "$@"; }


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
