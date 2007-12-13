#! /bin/bash

rm -rf test
hg init test
cd test

date >date
HGUSER=setup hg ci -Am '1000000: Init'

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

pass ci -m "$(bugid): A random bug"

pass ci -m "$(bugid): A random bug
$(bugid): Another random bug"

fail ci -m "$(bugid): A random bug
foo bar baz"

fail ci -m "$(bugid): A random bug [foo.bar]"
fail ci -m "123456: A short bugid"
fail ci -m "nobugid: No bugid"
fail ci -m "Blah blah"

pass ci -m "$(bugid): The next bug
Reviewed-by: mr"

pass ci -m "$(bugid): The next bug
Reviewed-by: mr, kgh"

fail ci -m "$(bugid): The next bug
Reviewed-by: "

fail ci -m "$(bugid): The next bug
Reviewed-by: Ben Bitdiddle"

pass ci -m "$(bugid): Another bug
Contributed-by: Ben Bitdiddle <ben@bits.org>"

pass ci -m "$(bugid): Another bug
Contributed-by: ben@bits.org"

pass ci -m "$(bugid): Another bug
Reviewed-by: iag
Contributed-by: Ben Bitdiddle <ben@bits.org>"

fail ci -m "$(bugid): Another bug
Contributed-by: Ben Bitdiddle"

fail ci -m "$(bugid): Another bug
Contributed-by: foo"

fail ci -m "$(bugid): Another bug
Reviewed-by:
Contributed-by: foo"
