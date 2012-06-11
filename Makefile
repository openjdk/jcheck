
VERSION = $(shell hg log -l1 --template '{node|short}' jcheck.py)
DATE = $(shell hg log -l1 --template '{date|isodatesec}' jcheck.py)

default: jcheck.py.pub

jcheck.py.pub: jcheck.py
	sed <$< >$@ \
	  -e "s/@VERSION@/$(VERSION)/" \
	  -e "s/@DATE@/$(DATE)/"


test: tests FORCE ; sh runtests.sh

test1: tests FORCE ; FAILFIRST=1 sh runtests.sh

tests: jcheck.py.pub mktests.sh ; sh mktests.sh


# The authoritative public copy is kept in its own little repo
# for easy access
#
dist: jcheck.py.pub
	@if [ "$$(hg st -m)" ]; then echo "Pending changes"; exit 1; fi
	cp -p $< dist/jcheck.py
	(cd dist; \
	 hg cat jcheck.py >/dev/null 2>&1 || hg add jcheck.py; \
	 hg ci -m "jcheck $(VERSION) $(DATE)" -d "$$d" \
	 && hg tip)


-include Local.gmk		# Define PUB and DST if needed

publish: jcheck.py.pub
	chmod g+w $<
	scp -p $< $(PUB)/jcheck.py

install: $(DST)/jcheck.py

$(DST)/%.py: %.py.pub
	$(INSTALL) -D -m 0644 $< $@


clean: ; rm -rf *~ *.pyc *.pub tests

.PHONY: FORCE dist publish
