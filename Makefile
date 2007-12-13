
test: tests FORCE ; sh runtests.sh

tests: mktests.sh ; sh mktests.sh

.PHONY: FORCE

clean: ; rm -rf *~ *.pyc tests
