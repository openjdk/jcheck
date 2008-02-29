
default: jcheck.py.pub

test: tests FORCE ; sh runtests.sh

test1: tests FORCE ; FAILFIRST=1 sh runtests.sh

tests: mktests.sh ; sh mktests.sh

.PHONY: FORCE

pub: jcheck.py.pub
	scp -p $< $(DST)/jcheck.py

jcheck.py.pub: jcheck.py
	sed <$< >$@ \
	  -e "s/@VERSION@/$$(hg id -i)/" \
	  -e "s/@DATE@/$$(hg log --template '{date|isodate}' -r tip)/"

clean: ; rm -rf *~ *.pyc *.pub tests
