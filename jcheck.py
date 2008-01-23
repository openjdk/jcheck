#
# Copyright 2007 Sun Microsystems, Inc.  All Rights Reserved.
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
# 
# This code is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 2 only, as
# published by the Free Software Foundation.
# 
# This code is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# version 2 for more details (a copy is included in the LICENSE file that
# accompanied this code).
# 
# You should have received a copy of the GNU General Public License version
# 2 along with this work; if not, write to the Free Software Foundation,
# Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
# 
# Please contact Sun Microsystems, Inc., 4150 Network Circle, Santa Clara,
# CA 95054 USA or visit www.sun.com if you need additional information or
# have any questions.
#

# JDK changeset checker

import re, os
from mercurial.node import *
from mercurial import cmdutil, patch, util, context, templater

Pass = False
Fail = True

def oneline(ctx):
    return ("%d:%s by %s on %s: %s\n"
            % (ctx.rev(), short(ctx.node()), ctx.user(),
               util.datestr(ctx.date(), format="%Y-%m-%d %H:%M",
                            timezone=False),
               ctx.description().splitlines()[0]))

def is_merge(repo, rev):
    return not (-1 in repo.changelog.parentrevs(rev))

# ## Stub: This will eventually query the db
def validate_author(an):
    return an != "fang"


# Comment validation

badwhite_re = re.compile("(\t)|([ \t]$)|\r", re.MULTILINE)

def badwhite_what(m):
    if m.group(1):
        return "Tab character"
    if m.group(2):
        return "Trailing whitespace"
    return "Carriage return (^M)"

base_addr_pat = "[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,4}"
addr_pat = ("(" + base_addr_pat + ")"
            + "|(([-_ a-zA-Z0-9]+) +<" + base_addr_pat + ">)")

bug_ident = re.compile("([0-9]+):")
bug_check = re.compile("([0-9]{7}): [^\[\]]*$")
sum_ident = re.compile("Summary:")
sum_check = re.compile("Summary: .*")
rev_ident = re.compile("Reviewed-by:")
rev_check = re.compile("Reviewed-by: (([a-z0-9]+)(, [a-z0-9]+)*$)")
con_ident = re.compile("Contributed-by:")
con_check = re.compile("Contributed-by: (" + addr_pat + ")$")

def bug_validate(ch, ctx, m):
    b = int(m.group(1))
    if b < 1000000:
        return "Bugid out of range"
    if b in ch.bugids:
        ch.error(ctx, "Bugid %d used more than once in this changeset" % b)
    ch.bugids.append(b)
    if b in ch.repo_bugids:
        r = ch.repo_bugids[b]
        if r < ctx.rev():
            ch.error(ctx, ("Bugid %d already used in this repository, in revision %d "
                           % (b, r)))

def rev_validate(ch, ctx, m):
    ans = re.split(", *", m.group(1))
    for an in ans:
        if not validate_author(an):
            ch.error(ctx, "Invalid reviewer name: %s" % an)

class State:
    def __init__(self, name, ident_pattern, check_pattern,
                 validator=None, min=0, max=1):
        self.name = name
        self.ident_pattern = ident_pattern
        self.check_pattern = check_pattern
        self.validator = validator
        self.min = min
        self.max = max

comment_grammar = [
    State("bugid line",
          bug_ident, bug_check, validator=bug_validate, min=1, max=1000),
    State("change summary",
          sum_ident, sum_check, min=0, max=1),
    State("reviewer attribution",
          rev_ident, rev_check, validator=rev_validate, min=1, max=1),
    State("contributor attribution",
          con_ident, con_check, min=0, max=1)
]

def repo_bugids(ui, repo):
    # Should cache this, eventually
    get = util.cachefunc(lambda r: repo.changectx(r).changeset())
    changeiter, matchfn = cmdutil.walkchangerevs(ui, repo, [], get,
                                                 { "rev" : ["0:tip"] })
    bugids = { }                        # bugid -> rev
    for st, rev, fns in changeiter:
        if st == 'add':
            node = repo.changelog.node(rev)
            ctx = context.changectx(repo, node)
            lns = ctx.description().splitlines()
            for ln in lns:
                m = bug_ident.match(ln)
                if m:
                    b = int(m.group(1))
                    if not b in bugids:
                        bugids[b] = rev
    if ui.debugflag:
        ui.debug("Bugids: %s\n" % bugids)
    return bugids


# Checker class

class checker(object):

    def __init__(self, ui, repo, repo_bugids):
        self.ui = ui
        self.repo = repo
        self.rv = Pass
        self.checks = [c for c in checker.__dict__ if c.startswith("c_")]
        self.checks.sort()
        self.summarized = False
        self.repo_bugids = repo_bugids
        self.bugids = [ ]               # Bugids in current changeset

    def summarize(self, ctx):
        self.ui.status("\n")
        self.ui.status("> Changeset: %d:%s\n" % (ctx.rev(), short(ctx.node())))
        self.ui.status("> Author:    %s\n" % ctx.user())
        self.ui.status("> Date:      %s\n" % templater.isodate(ctx.date()))
        self.ui.status(">\n> ")
        self.ui.status("\n> ".join(ctx.description().splitlines()))
        self.ui.status("\n\n")
        self.summarized = True

    def error(self, ctx, msg):
        if not self.summarized:
            self.summarize(ctx)
        self.ui.status(msg + "\n")
        self.rv = Fail

    def c_00_author(self, ctx):
        self.ui.debug("author: %s\n" % ctx.user())
        if not validate_author(ctx.user()):
            self.error(ctx, "Invalid changeset author")

    def c_01_comment(self, ctx):
        m = badwhite_re.search(ctx.description())
        if m:
            ln = ctx.description().count("\n", 0, m.start()) + 1
            self.error(ctx, "%s in comment (line %d)" % (badwhite_what(m), ln))

        if is_merge(self.repo, ctx.rev()):
            if ctx.description() != "Merge":
                self.error(ctx, ("Invalid comment for merge changeset"
                                 + " (must be \"Merge\")"))
            return

        lns = ctx.description().splitlines()

        i = 0                           # Input index
        gi = 0                          # Grammar index
        n = 0                           # Occurrence count
        while i < len(lns):
            ln = lns[i]
            st = comment_grammar[gi]
            n = 0
            while (st.ident_pattern.match(ln)):
                m = st.check_pattern.match(ln)
                if not m:
                    self.error(ctx, "Invalid %s" % st.name)
                elif st.validator:
                    st.validator(self, ctx, m)
                n = n + 1
                i = i + 1
                if i >= len(lns):
                    break;
                ln = lns[i]
            if n < st.min:
                self.error(ctx, "Incomplete comment: Missing %s" % st.name)
            if n > st.max:
                self.error(ctx, "Too many %ss" % st.name)
            gi = gi + 1
            if gi >= len(comment_grammar):
                break

        if (gi == 0 and n > 0):
            self.error(ctx, "Incomplete comment: Missing bugid line")
        elif gi == 1 or (gi == 2 and n == 0):
            self.error(ctx, "Incomplete comment: Missing reviewer attribution")
        if (i < len(lns)):
            self.error(ctx, "Extraneous text")

    def c_02_files(self, ctx):
        changes = self.repo.status(ctx.parents()[0].node(),
                                   ctx.node(), None)[:5]
        modified, added = changes[:2]
        # ## Skip files that were renamed but not modified
        files = modified + added
        self.ui.note("Checking files: %s\n" % ", ".join(files))
        for f in files:
            fx = ctx.filectx(f)
            data = fx.data()
            m = badwhite_re.search(data)
            if m:
                ln = data.count("\n", 0, m.start()) + 1
                self.error(ctx, "%s:%d: %s" % (f, ln, badwhite_what(m)))
            ## check_file_header(self, fx, data)
            fm = fx.manifest()
            if fm.execf(f):
                self.error(ctx, "%s: Executable files not permitted" % f)
            if fm.linkf(f):
                self.error(ctx, "%s: Symbolic links not permitted" % f)

    def check(self, node):
        self.summarized = False
        self.bugids = [ ]
        ctx = context.changectx(self.repo, node)
        self.ui.debug(oneline(ctx))
        for c in self.checks:
            cf = checker.__dict__[c]
            cf(self, ctx)
        return self.rv


def hook(ui, repo, hooktype, node=None, source=None, **kwargs):
    ui.debug("jcheck: node %s, source %s, args %s\n" % (node, source, kwargs))
    if not repo.local():
        raise util.Abort("repository '%s' is not local" % repo.path)
    if not os.path.exists(os.path.join(repo.root, ".jcheck")):
        ui.note("jcheck not enabled (no .jcheck in repository root); skipping\n")
        return Pass
    ch = checker(ui, repo, repo_bugids(ui, repo))
    firstnode = bin(node)
    start = repo.changelog.rev(firstnode)
    end = repo.changelog.count()
    for rev in xrange(start, end):
        ch.check(repo.changelog.node(rev))
    if ch.rv == Fail:
        ui.status("\n")
    return ch.rv


def jcheck(ui, repo, **opts):
    """check changesets against JDK standards"""
    ui.debug("jcheck repo=%s opts=%s\n" % (repo.path, opts))
    if not repo.local():
        raise util.Abort("repository '%s' is not local" % repo.path)
    if not os.path.exists(os.path.join(repo.root, ".jcheck")):
        ui.status("jcheck not enabled (no .jcheck in repository root)\n")
        return Pass
    if len(opts["rev"]) == 0:
        opts["rev"] = ["tip"]

    get = util.cachefunc(lambda r: repo.changectx(r).changeset())
    changeiter, matchfn = cmdutil.walkchangerevs(ui, repo, [], get, opts)

    if ui.debug:
        displayer = cmdutil.show_changeset(ui, repo, opts, True, matchfn)
    ch = checker(ui, repo, repo_bugids(ui, repo))
    for st, rev, fns in changeiter:
        if st == 'add':
            node = repo.changelog.node(rev)
            parents = [p for p in repo.changelog.parentrevs(rev)
                       if p != nullrev]
            if ui.debugflag:
                displayer.show(rev, node, copies=False)
            ch.check(node)
        elif st == 'iter':
            if ui.debugflag:
                displayer.flush(rev)
    if ch.rv == Fail:
        ui.status("\n")
    return ch.rv

opts = [("r", "rev", [], "check the specified revision or range (default: tip)")]

help = "[-r rev]"

cmdtable = {
    "jcheck": (jcheck, opts, "hg jcheck [-r rev]")
}
