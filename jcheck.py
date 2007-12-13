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

addr_pat = "[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,4}"
addr_re = re.compile("(^" + addr_pat + "$)"
                     + "|((^[-_ a-zA-Z0-9]+) +<" + addr_pat + ">$)")

def validate_addr(a):
    return bool(addr_re.match(a))

desc_pattern = re.compile("(([0-9]{7}): [^\[\]]*$)"
                          "|(Reviewed-by: (([a-z0-9]+)(, [a-z0-9]+)*$))"
                          "|(Contributed-by: ([^ ].*)$)")

def oneline(ctx):
    return ("%d:%s by %s on %s: %s\n"
            % (ctx.rev(), short(ctx.node()), ctx.user(),
               util.datestr(ctx.date(), format="%Y-%m-%d %H:%M",
                            timezone=False),
               ctx.description().splitlines()[0]))

class checker(object):

    def __init__(self, ui, repo):
        self.ui = ui
        self.repo = repo
        self.rv = Pass
        self.checks = [c for c in checker.__dict__ if c.startswith("c_")]
        self.checks.sort()
        self.summarized = False
        self.current_check = None
        self.failed_checks = { }

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
        self.ui.warn(msg)
        self.failed_checks[self.current_check] = True
        self.rv = Fail

    def c_00_author(self, ctx):
        self.ui.debug("author: %s\n" % ctx.user())

    def c_01_description(self, ctx):

        """
        Each line of a changeset comment must be of one of the following forms:

          - A bug id, a colon, and the bug's synopsis:

              1234567: Long.MAX_VALUE is too small

            The bug id must not have been used previously.  The synopsis must
            not include reviewer names in brackets.

          - A reviewer attribution:

              Reviewed-by: foo, bar

            The names must be valid JDK author names.  A reviewer attribution
            must follow a bug-id line.

          - A contributor attribution:

              Contributed-by: Ben Bitdiddle <ben@bits.org>

            The e-mail address must be valid per RFC 822.  A contributor
            attribution must follow a bug-id line or a reviewer attribution.
        """

        ## Should enforce order: Bug id, reviewers, contributor
        lns = ctx.description().splitlines()
        self.ui.debug("description: %s\n" % lns[0])
        for ln in lns:
            m = desc_pattern.match(ln)
            if not m:
                self.error(ctx, "Invalid comment line: %s\n" % ln)
                continue
            if m.group(7):
                contributor = m.group(8)
                if not validate_addr(contributor):
                    self.error(ctx, ("Invalid contributor e-mail address: %s\n"
                                     % contributor))

    def check(self, node):
        self.summarized = False
        ctx = context.changectx(self.repo, node)
#        self.ui.debug(oneline(ctx))
        for c in self.checks:
            cf = checker.__dict__[c]
            self.current_check = cf
            cf(self, ctx)
        return self.rv

    def advise(self):
        if self.ui.verbose and self.failed_checks:
            fc = list(self.failed_checks.keys())
            fc.sort()
            for cf in fc:
                advice = cf.__doc__
                if advice:
                    for ln in advice.splitlines():
                        self.ui.warn(ln[8:] + "\n")

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
    ch.advise()
    return ch.rv

opts = [("r", "rev", [], "check the specified revision or range (default: tip)")]

help = "[-r rev]"

cmdtable = {
    "jcheck": (jcheck, opts, "hg jcheck [-r rev]")
}
