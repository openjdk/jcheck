
default: jcheck.py.pub

test: tests FORCE ; sh runtests.sh

test1: tests FORCE ; FAILFIRST=1 sh runtests.sh

tests: jcheck.py.pub mktests.sh ; sh mktests.sh

publish: jcheck.py.pub
	chmod g+w $<
	scp -p $< $(DST)/jcheck.py

jcheck.py.pub: jcheck.py
	sed <$< >$@ \
	  -e "s/@VERSION@/$$(hg id -i)/" \
	  -e "s/@DATE@/$$(hg log --template '{date|isodatesec}' -r tip)/"

dist: jcheck.py.pub
	@if [ "$$(hg st -m)" ]; then echo "Pending changes"; exit 1; fi
	cp -p $< dist/jcheck.py
	(cd dist; \
	 hg cat jcheck.py >/dev/null 2>&1 || hg add jcheck.py; \
	 d="$$(hg log --template '{date|isodatesec}' -r tip -R ..)"; \
	 hg ci -m "jcheck $$(hg id -i -R ..) $$d" -d "$$d" \
	 && hg tip)

clean: ; rm -rf *~ *.pyc *.pub tests

.PHONY: FORCE dist
