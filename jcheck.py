#
# Copyright 2007-2009 Sun Microsystems, Inc.  All Rights Reserved.
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

# Configuration
#
# In your ~/.hgrc add the following:
#
#   [extensions]
#   jcheck = /path/to/jcheck.py
#
# This will enable the "hg jcheck" subcommand.  "hg help jcheck" will describe
# the available options.
#
# It is additionally recommended that you define the following hooks so that
# you never create invalid changesets in a working JDK repository:
#
#   [hooks]
#   pretxnchangegroup.jcheck = python:jcheck.hook
#   pretxncommit.jcheck = python:jcheck.hook
#
# This extension only enforces its checks if the root of the repository upon
# which it is invoked contains a directory named ".jcheck", so these hooks will
# not interfere with Mercurial operations upon non-JDK repositories.
#
# This extension requires the descriptions of merge changesets to say simply
# "Merge" rather than, say, "Automated merge with file:///u/mr/ws/jdk7/..."
# because the latter contains potentially-confidential information.  If you
# have enabled the "fetch" extension it is therefore also recommended that you
# add the following to your ~/.hgrc:
#
#   [defaults]
#   fetch = -m Merge

_version = "@VERSION@"
_date = "@DATE@"

import sys, os, re, urllib, urllib2
from mercurial.node import *
from mercurial import cmdutil, patch, util, context, templater

Pass = False
Fail = True

def datestr(ctx):
    # Mercurial 0.9.5 and earlier append a time zone; strip it.
    return util.datestr(ctx.date(), format="%Y-%m-%d %H:%M")[:16]
    
def oneline(ctx):
    return ("%5d:%s  %-12s  %s  %s\n"
            % (ctx.rev(), short(ctx.node()), ctx.user(), datestr(ctx),
               ctx.description().splitlines()[0]))

def is_merge(repo, rev):
    return not (-1 in repo.changelog.parentrevs(rev))


# Configuration-file parsing

def load_conf(root):
    cf = { }
    fn = os.path.join(root, ".jcheck/conf")
    f = open(fn)
    try:
        prop_re = re.compile("\s*(\S+)\s*=\s*(\S+)\s*$")
        i = 0
        for ln in f.readlines():
            i = i + 1
            ln = ln.strip()
            if (ln.startswith("#")):
                continue
            m = prop_re.match(ln)
            if not m:
                raise util.Abort("%s:%d: Invalid configuration syntax: %s"
                                 % (fn, i, ln))
            cf[m.group(1)] = m.group(2)
    finally:
        f.close()
    for pn in ["project"]:
        if not cf.has_key(pn):
            raise util.Abort("%s: Missing property: %s" % (fn, pn))
    return cf


# Author validation

author_cache = { }                      ## Should really cache more permanently

def validate_author(an, pn):
  if author_cache.has_key(an):
    return True
  u = ("http://db.openjdk.java.net/people/%s/projects/%s"
       % (urllib.quote(an), pn))
  f = None
  try:
      try:
          f = urllib2.urlopen(u)
      except urllib2.HTTPError, e:
          if e.code == 404:
              return False
          raise e
  finally:
      if f:
          f.close()
  author_cache[an] = True
  return True


# Whitespace and comment validation

badwhite_re = re.compile("(\t)|([ \t]$)|\r", re.MULTILINE)
normext_re = re.compile(".*\.(java|c|h|cpp|hpp)$")

tag_desc_re = re.compile("Added tag [^ ]+ for changeset [0-9a-f]{12}")
tag_re = re.compile("tip|jdk[67]-b\d{2,3}|hs\d\d.\d-b\d\d")

def badwhite_what(m):
    if m.group(1):
        return "Tab character"
    if m.group(2):
        return "Trailing whitespace"
    return "Carriage return (^M)"

base_addr_pat = "[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,4}"
addr_pat = ("(" + base_addr_pat + ")"
            + "|(([-_a-zA-Z0-9][-_ a-zA-Z0-9]+) +<" + base_addr_pat + ">)")

bug_ident = re.compile("([0-9]+):")
bug_check = re.compile("([0-9]{7}): \S.*$")
sum_ident = re.compile("Summary:")
sum_check = re.compile("Summary: \S.*")
rev_ident = re.compile("Reviewed-by:")
rev_check = re.compile("Reviewed-by: (([a-z0-9]+)(, [a-z0-9]+)*$)")
con_ident = re.compile("Contributed-by:")
con_check = re.compile("Contributed-by: ((" + addr_pat + ")(, (" + addr_pat + "))*)$")

def bug_validate(ch, ctx, m, pn):
    bs = m.group(1)
    if not (bs[0] in ['1','2','4','5','6']):
        ch.error(ctx, "Invalid bugid: %s" % bs)
    b = int(bs)
    if b in ch.cs_bugids:
        ch.error(ctx, "Bugid %d used more than once in this changeset" % b)
    ch.cs_bugids.append(b)
    if b in ch.repo_bugids:
        r = ch.repo_bugids[b]
        if r < ctx.rev():
            ch.error(ctx, ("Bugid %d already used in this repository, in revision %d "
                           % (b, r)))

def rev_validate(ch, ctx, m, pn):
    ans = re.split(", *", m.group(1))
    for an in ans:
        if not validate_author(an, pn):
            ch.error(ctx, "Invalid reviewer name: %s" % an)
        ch.cs_reviewers.append(an)

def con_validate(ch, ctx, m, pn):
    ch.cs_contributor = m.group(1)

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
          con_ident, con_check, validator=con_validate, min=0, max=1)
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



# Black/white lists
## The black/white lists should really be in the database

# Bogus yet historically-accepted changesets,
# so that jcheck may evolve
#
changeset_whitelist = [
    '31000d79ec713de1e601dc16d74d726edd661ed5',
    'b7987d19f5122a9f169e568f935b7cdf1a2609f5',
    'c70a245cad3ad74602aa26b9d8e3d0472f7317c3',
    'e8e20316458c1cdb85d9733a2e357e438a76a859',
    'f68325221ce1efe94ab367400a49a8039d9b3db3' ]

# Bad changesets that should never be allowed in
#
changeset_blacklist = [
    'd3c74bae36884525be835ea428293bb6e7fa54d3',
    '2bb5ef5c8a2dc0a32b1cd67803128ce12cad461e',
    '4ff95cec682e67a374f9c5725d1879f43624d888',
    '75f1884152db275047a09aa6085ae7c49e3f4126',
    '6ecad8bfb1e5d34aef2ca61d30c1d197745d6844' ]



# Checker class

class checker(object):

    def __init__(self, ui, repo, repo_bugids, strict):
        self.ui = ui
        self.repo = repo
        self.rv = Pass
        self.checks = [c for c in checker.__dict__ if c.startswith("c_")]
        self.checks.sort()
        self.summarized = False
        self.repo_bugids = repo_bugids
        self.cs_bugids = [ ]            # Bugids in current changeset
        self.cs_author = None           # Author of current changeset
        self.cs_reviewers = [ ]         # Reviewers of current changeset
        self.cs_contributor = None      # Contributor of current changeset
        self.strict = strict
        self.conf = load_conf(repo.root)
        self.whitespace_lax = False
        if self.conf.has_key("whitespace") and self.conf["whitespace"] == "lax":
            self.whitespace_lax = True

    def summarize(self, ctx):
        self.ui.status("\n")
        self.ui.status("> Changeset: %d:%s\n" % (ctx.rev(), short(ctx.node())))
        self.ui.status("> Author:    %s\n" % ctx.user())
        self.ui.status("> Date:      %s\n" % datestr(ctx))
        self.ui.status(">\n> ")
        self.ui.status("\n> ".join(ctx.description().splitlines()))
        self.ui.status("\n\n")

    def error(self, ctx, msg):
        if not self.summarized:
            if ctx:
                self.summarize(ctx)
            else:
                self.ui.status("\n")
            self.summarized = True
        self.ui.status(msg + "\n")
        self.rv = Fail

    def c_00_author(self, ctx):
        self.ui.debug("author: %s\n" % ctx.user())
        if not validate_author(ctx.user(), self.conf["project"]):
            self.error(ctx, "Invalid changeset author: %s" % ctx.user())
        self.cs_author = ctx.user()

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

        if tag_desc_re.match(ctx.description()):
            ## Should check tag itself
            return

        if (ctx.rev() == 0
            and ctx.user() == "duke"
            and ctx.description().startswith("Initial load")):
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
                    st.validator(self, ctx, m, self.conf["project"])
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

        if not self.cs_contributor and [self.cs_author] == self.cs_reviewers:
            self.error(ctx, "Self-reviews not permitted")
        if (gi == 0 and n > 0):
            self.error(ctx, "Incomplete comment: Missing bugid line")
        elif gi == 1 or (gi == 2 and n == 0):
            self.error(ctx, "Incomplete comment: Missing reviewer attribution")
        if (i < len(lns)):
            self.error(ctx, "Extraneous text in comment")

    def c_02_files(self, ctx):
        changes = self.repo.status(ctx.parents()[0].node(),
                                   ctx.node(), None)[:5]
        modified, added = changes[:2]
        # ## Skip files that were renamed but not modified
        files = modified + added
        self.ui.debug("Checking files: %s\n" % ", ".join(files))
        for f in files:
            if ctx.rev() == 0:
                ## This is loathsome
                if f.startswith("test/java/rmi"): continue
                if f.startswith("test/com/sun/javadoc/test"): continue
                if f.startswith("docs/technotes/guides"): continue
            fx = ctx.filectx(f)
            if normext_re.match(f) and not self.whitespace_lax:
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

    def c_03_hash(self, ctx):
        if hex(ctx.node()) in changeset_blacklist:
            self.error(ctx, "Blacklisted changeset: %s" % hex(ctx.node()))

    def check(self, node):
        self.summarized = False
        self.cs_bugids = [ ]
        self.cs_author = None
        self.cs_reviewers = [ ]
        self.cs_contributor = None
        ctx = context.changectx(self.repo, node)
        self.ui.note(oneline(ctx))
        if hex(node) in changeset_whitelist:
            self.ui.note("%s in whitelist; skipping\n" % hex(node))
            return Pass
        for c in self.checks:
            cf = checker.__dict__[c]
            cf(self, ctx)
        return self.rv

    def check_repo(self):

        ts = self.repo.tags().keys()
        for t in ts:
            if not tag_re.match(t):
                self.error(None,
                           "Illegal tag name: %s" % t)

        bs = self.repo.branchtags()
        if len(bs) > 1:
            bs = bs.copy()
            del bs["default"]
            self.error(None,
                       "Named branches not permitted; this repository has: %s"
                       % ", ".join(bs.keys()))

        if self.strict:
            nh = len(self.repo.heads())
            if nh > 1:
                self.error(None,
                           "Multiple heads not permitted; this repository has %d"
                           % nh)

        return self.rv


def hook(ui, repo, hooktype, node=None, source=None, **opts):
    ui.debug("jcheck: node %s, source %s, args %s\n" % (node, source, opts))
    if not repo.local():
        raise util.Abort("repository '%s' is not local" % repo.path)
    if not os.path.exists(os.path.join(repo.root, ".jcheck")):
        ui.note("jcheck not enabled (no .jcheck in repository root); skipping\n")
        return Pass
    strict = opts.has_key("strict") and opts["strict"]
    ch = checker(ui, repo, repo_bugids(ui, repo), strict)
    ch.check_repo()
    firstnode = bin(node)
    start = repo.changelog.rev(firstnode)
    end = repo.changelog.count()
    for rev in xrange(start, end):
        ch.check(repo.changelog.node(rev))
    if ch.rv == Fail:
        ui.status("\n")
    return ch.rv


# Run this hook in repository gates

def strict_hook(ui, repo, hooktype, node=None, source=None, **opts):
    opts["strict"] = True
    return hook(ui, repo, hooktype, node, source, **opts)


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

    ch = checker(ui, repo, repo_bugids(ui, repo), False)
    ch.check_repo()

    get = util.cachefunc(lambda r: repo.changectx(r).changeset())
    changeiter, matchfn = cmdutil.walkchangerevs(ui, repo, [], get, opts)
    if ui.debug:
        displayer = cmdutil.show_changeset(ui, repo, opts, True, matchfn)
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

opts = [("r", "rev", [], "check the specified revision or range (default: tip)"),
        ("s", "strict", False, "check everything")]

help = "[-r rev] [-s]"

cmdtable = {
    "jcheck": (jcheck, opts, "hg jcheck " + help)
}
