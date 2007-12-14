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

import re
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

def bug_validate(m):
    if int(m.group(1)) < 1000000:
        return "Bugid out of range"
    return None

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
          rev_ident, rev_check, min=1, max=1),
    State("contributor attribution",
          con_ident, con_check, min=0, max=1)
]

class checker(object):

    def __init__(self, ui, repo):
        self.ui = ui
        self.repo = repo
        self.rv = Pass
        self.checks = [c for c in checker.__dict__ if c.startswith("c_")]
        self.checks.sort()
        self.summarized = False

    def summarize(self, ctx):
        self.ui.warn("\n")
        self.ui.warn("> Changeset: %d:%s\n" % (ctx.rev(), short(ctx.node())))
        self.ui.warn("> Author:    %s\n" % ctx.user())
        self.ui.warn("> Date:      %s\n" % templater.isodate(ctx.date()))
        self.ui.warn(">\n> ")
        self.ui.warn("\n> ".join(ctx.description().splitlines()))
        self.ui.warn("\n\n")
        self.summarized = True

    def error(self, ctx, msg):
        if not self.summarized:
            self.summarize(ctx)
        self.ui.warn(msg + "\n")
        self.rv = Fail

    def c_00_author(self, ctx):
        self.ui.debug("author: %s\n" % ctx.user())

    def c_01_comment(self, ctx):
        lns = ctx.description().splitlines()
        self.ui.debug("comment: %s\n" % lns[0])

        i = 0                           # Input index
        gi = 0                          # Grammar index
        n = 0                           # Occurrence count
        while i < len(lns):
            if self.ui.debugflag:
                print "## top [%d] %d %d" % (i, gi, n)
            ln = lns[i]
            st = comment_grammar[gi]
            n = 0
            while (st.ident_pattern.match(ln)):
                m = st.check_pattern.match(ln)
                if not m:
                    self.error(ctx, "Invalid %s" % st.name)
                elif st.validator:
                    v = st.validator(m)
                    if v:
                        self.error(ctx, v)
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

        if self.ui.debugflag:
            print "## end [%d] %d %d" % (i, gi, n)
        if (gi == 0 and n > 0):
            self.error(ctx, "Incomplete comment: Missing bugid line")
        elif gi == 1 or (gi == 2 and n == 0):
            self.error(ctx, "Incomplete comment: Missing reviewer attribution")
        if (i < len(lns)):
            self.error(ctx, "Extraneous text")

    def check(self, node):
        self.summarized = False
        ctx = context.changectx(self.repo, node)
        self.ui.debug(oneline(ctx))
        for c in self.checks:
            cf = checker.__dict__[c]
            cf(self, ctx)
        return self.rv

## broken right now
def hook(ui, repo, hooktype, node=None, source=None, **kwargs):
    ui.debug("jcheck: node %s, source %s, args %s\n" % (node, source, kwargs))
    ch = checker(ui, repo)
    return ch.check(node)


def jcheck(ui, repo, **opts):
    """check changesets against JDK standards"""
    ui.debug("jcheck repo=%s opts=%s\n" % (repo.path, opts))
    if not repo.local():
        raise util.Abort("repository '%s' is not local" % repo.path)
    if len(opts["rev"]) == 0:
        opts["rev"] = ["tip"]

    get = util.cachefunc(lambda r: repo.changectx(r).changeset())
    changeiter, matchfn = cmdutil.walkchangerevs(ui, repo, [], get, opts)

    if ui.debug:
        displayer = cmdutil.show_changeset(ui, repo, opts, True, matchfn)
    ch = checker(ui, repo)
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
    return ch.rv

opts = [("r", "rev", [], "check the specified revision or range (default: tip)")]

help = "[-r rev]"

cmdtable = {
    "jcheck": (jcheck, opts, "hg jcheck [-r rev]")
}
