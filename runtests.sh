#! /bin/bash

cd $(dirname $0)/tests

last=$(hg tip --template '{rev}')

failures=0

fail() {
  echo "-- $r: TEST FAILED"
  failures=$(expr $failures + 1)
  if [ $FAILFIRST ]; then exit 2; fi
}

r=0
while [ $r -le $last ]; do
  type=$(hg log -r $r --template '{author}')
  echo "-- $r $type"
  if [ $type = setup ]; then
    r=$(expr $r + 1)
    continue
  fi
  hg jcheck -r $r "$@"
  rv=$?
  case $type in
    pass) if [ $rv != 0 ]; then fail $r; fi;;
    fail) if [ $rv == 0 ]; then fail $r; fi;;
  esac
  r=$(expr $r + 1)
done

if [ $failures -gt 0 ]; then
  echo "-- FAILURES: $failures"
else
  echo "-- All tests passed"
fi
[ $failures != 0 ] && exit 1 || exit 0
