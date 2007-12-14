
test: tests FORCE ; sh runtests.sh

test1: tests FORCE ; FAILFIRST=1 sh runtests.sh

tests: mktests.sh ; sh mktests.sh

.PHONY: FORCE

clean: ; rm -rf *~ *.pyc tests
