#
# Copyright (c) 2007, 2012, Oracle and/or its affiliates. All rights reserved.
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
# Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
# or visit www.oracle.com if you need additional information or have any
# questions.
#


# JDK changeset checker

# Quick configuration: Add the following to your ~/.hgrc:
#
#   [extensions]
#   jcheck = /path/to/jcheck.py
#
#   # Omit these lines if you use Mercurial Queues
#   [hooks]
#   pretxnchangegroup.jcheck = python:jcheck.hook
#   pretxncommit.jcheck = python:jcheck.hook
#
#   # Include this if you use the (deprecated) Mercurial "fetch" extension
#   [defaults]
#   fetch = -m Merge
#
# For more information: http://openjdk.java.net/projects/code-tools/jcheck/

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

_matchall = getattr(cmdutil, 'matchall', None)
if not _matchall:
    try:
        from mercurial import scmutil
        _matchall = scmutil.matchall
    except ImportError:
        pass

def repocompat(repo):
    # Modern mercurial versions use len(repo) and repo[cset_id]; enable those
    # operations with older versions.
    t = type(repo)
    if not getattr(t, '__len__', None):
        def repolen(self):
            return self.changelog.count()
        setattr(t, '__len__', repolen)
    if not getattr(t, '__getitem__', None):
        def repoitem(self, arg):
            return context.changectx(self, arg)
        setattr(t, '__getitem__', repoitem)
    # Similarly, use branchmap instead of branchtags; enable it if needed.
    if not getattr(t, 'branchmap', None):
        setattr(t, 'branchmap', t.branchtags)


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
tag_re = re.compile("tip$|jdk[4-9](u\d{1,2})?-b\d{2,3}$|hs\d\d(\.\d{1,2})?-b\d\d$")

def badwhite_what(m):
    if m.group(1):
        return "Tab character"
    if m.group(2):
        return "Trailing whitespace"
    return "Carriage return (^M)"

base_addr_pat = "[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,4}"
addr_pat = ("(" + base_addr_pat + ")"
            + "|(([-_a-zA-Z0-9][-_ a-zA-Z0-9]+) +<" + base_addr_pat + ">)")

bug_ident = re.compile("(([A-Z][A-Z0-9]+-)?[0-9]+):")
bug_check = re.compile("([0-9]{7}): \S.*$")
sum_ident = re.compile("Summary:")
sum_check = re.compile("Summary: \S.*")
rev_ident = re.compile("Reviewed-by:")
rev_check = re.compile("Reviewed-by: (([a-z0-9]+)(, [a-z0-9]+)*$)")
con_ident = re.compile("Contributed-by:")
con_check = re.compile("Contributed-by: ((" + addr_pat + ")(, (" + addr_pat + "))*)$")

def bug_validate(ch, ctx, m, pn):
    bs = m.group(1)
    if not (bs[0] in ['1','2','4','5','6','7','8']):
        ch.error(ctx, "Invalid bugid: %s" % bs)
    b = int(bs)
    if b in ch.cs_bugids:
        ch.error(ctx, "Bugid %d used more than once in this changeset" % b)
    ch.cs_bugids.append(b)
    if not ch.bugids_allow_dups and b in ch.repo_bugids:
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

def checked_comment_line(ln):
    for st in comment_grammar:
        if st.ident_pattern.match(ln):
            return True
    return False

def repo_bugids(ui, repo):
    def addbugids(bugids, ctx):
        lns = ctx.description().splitlines()
        for ln in lns:
            m = bug_check.match(ln)
            if m:
                b = int(m.group(1))
                if not b in bugids:
                    bugids[b] = ctx.rev()
        
    # Should cache this, eventually
    bugids = { }                        # bugid -> rev
    opts = { 'rev' : ['0:tip'] }
    try:
        nop = lambda c, fns: None
        iter = cmdutil.walkchangerevs(repo, _matchall(repo), opts, nop)
        for ctx in iter:
            addbugids(bugids, ctx)
    except (AttributeError, TypeError):
        # AttributeError:  matchall does not exist in hg < 1.1
        # TypeError:  walkchangerevs args differ in hg <= 1.3.1
        get = util.cachefunc(lambda r: repo.changectx(r).changeset())
        changeiter, matchfn = cmdutil.walkchangerevs(ui, repo, [], get, opts)
        for st, rev, fns in changeiter:
            if st == 'add':
                node = repo.changelog.node(rev)
                addbugids(bugids, context.changectx(repo, node))
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
    'f68325221ce1efe94ab367400a49a8039d9b3db3',
    '4dfa5d67c44500155ce9ab1e00d0de21bdbb9ee6',
    '73a4d5be86497baf74c1fc194c9a0dd4e86d3a31', # jdk6/jdk6/jaxp bad comment
    'a25f15bfd04b46a302b6ca1a298c176344f432dd', # jdk6/jdk6/jdk  bad comment
    'bf87d5af43614d609a5251c43eea44c028500d02', # jdk6/jdk6/jdk  bad comment
    'd77434402021cebc4c25b452db18bbfd2d7ccda1', # jdk6/jdk6/jdk  bad comment
    '931e5f39e365a0d550d79148ff87a7f9e864d2e1', # hotspot dup bug id 7147064
    'd8abc90163a4b58db407a60cba331ab21c9977e7', # hotspot dup bug id 7147064
    '45849c62c298aa8426c9e67599e4e35793d8db13', # pubs executable files
    '38050e6655d8acc220800a28128cef328906e825', # pubs invalid bugid line
    # hotspot/test/closed no Reviewed-by line
    '8407fef5685f32ed42b79c5d5f13f6c8007171ac',
    ]

# Bad changesets that should never be allowed in
#
changeset_blacklist = [
    'd3c74bae36884525be835ea428293bb6e7fa54d3',
    '2bb5ef5c8a2dc0a32b1cd67803128ce12cad461e',
    '4ff95cec682e67a374f9c5725d1879f43624d888',
    '75f1884152db275047a09aa6085ae7c49e3f4126',
    '6ecad8bfb1e5d34aef2ca61d30c1d197745d6844',
    '4ec7d1890538c54a3cc7559e88db5a5e3371fe5d',
    '669768c591ac438f4ca26d5cbdde7486ce49a2e2',
    '2ded3bb1452943d5273e7b83af9609ce6511a105',
    # hsdev/hotspot/{hotspot,master} dup bugid 7019157
    '0d8777617a2d028ba0b82943c829a5c6623f1479',
    # hsx/hotspot-comp/jdk dup bugid 7052202 + follow-on cset
    'ad2d483067099421f3ea4492269cce69009b046f',
    '521e2254994c76441c25f4374e16abbe314d8143',
    # hsx/hotspot-rt/hotspot wrong bugid 7059288 + associated merge
    'aa5f3f5978991182b8dbbd2b46fdcb47b6371dd9',
    '709d9389b2bc290dad5a35ec5b5f951b07ce9631',
    # jdk8/awt/jdk dup bugid 7100054
    'f218e6bdf1e8e20ca3f0fdaeb29c38f56afdf988',
    # jdk7u/jdk7u-dev/jaxp mistaken push
    '24f4c1185305b60818d255550a0fdc1ddf52c2a6',
    # jdk8/build/pubs executable file
    '2528f2a1117000eb98891a139e8f839fc5e2bfab',
    # jdk8/2d/jdk/src/closed security fix in wrong forest
    '8c7fbf082af5ec6d7ad0b1789cedc98a597f1f83',
    # jdk7u/jdk7u5/jdk bad fix for 6648202
    'b06f6d9a6c329792401b954682d49169484b586d',
    # hsx/hsx24/hotspot/src/closed bad merge
    '306614eb47a79e6d25a8c7447d0fe47fac28b24c',
    # hsx/hsx24/hotspot/test/closed bad merge
    '96163ee390bf223fe0037739fc953e8ed7d49560',
    # jdk8/awt/jdk INTJDK-7600365
    '6be9b0bda6dccbfc738b9173a71a15dcafda4f3b',
    # jdk8/tl/jdk/test/closed INTJDK-7600460
    '9eb97a2b3274edff83a362f76bbadb866a97a89b',
    # jdk7u11-dev/jaxp bad fix for 7192390
    '1642814c94fd0206f8b4f460cc77fa6fc099731a',
    # jdk7u11-dev/jdk bad fix for 7192390
    '90eb0407ca69dc572d20490f17239b183bb616b6',
    # jdk7u11-dev/jdk/test/closed bad fix for 7192390
    '512af24c6909ef2c766c3a5217c719545de68bf7',
    # jdk7u11-dev/jdk redone rmi fix
    'fd6ce0200a7f519380e6863930e92f9182030fa0',
    # jdk7u11-dev/jdk/test/closed redone rmi fix
    '770d9cf0e1dc97f7aaa3fdfbb430b27a40b1a3a9',
    # jdk7u13-dev/jdk bad fix for 8006611
    '12b6a43f9fefa6c3bbf81d9096e764e72bacf065',
    # jdk8/nashorn unwanted tag jdk8-b78
    '8f49d8121c7e63d22f55412df4ff4800599686d6',
    # hsx/hotspot-emb/hotspot wrong bugid 8009004
    '29ab68ef5bb643f96218126dc2ff845561d552a4',
    # jdk7u40/jdk/src/closed mistaken push 8016315
    'd2b0a0c38c808bddff604a025469c5102a62edfe',
    # jdk7u40/jdk/test/closed mistaken push 8016622
    'd1e0d129aa0fccdc1ff1bcf20f126ffea900f30b',
    # hsx/hotspot-gc/hotspot wrong bugid 8024547
    '9561e0a8a2d63c45e751755d791e25396d94025a',
    # jdk8/ds/install dup bugid 8024771
    '835ef04a36e5fe95d4c0deb6e633371053f3cbba',
    # jdk5u/jdk5.0u55/j2se bad fix 8025034
    'e18574aa4be397b83a43e1444cb96c903f152fcb',
    # jdk6u/jdk6u65/j2se bad fix 8025034
    'a0f1589decc6181a5e048e48058d12cfa68cd3e1',
    # jdk7u/jdk7u45/j2se bad fix 8025034
    '0a312c04dbc8d33601efecfb0d23b8c09bf088fe',
    # jdk8/build/pubs executable files
    '3ecd3336c805978a37a933fbeca26c65fbe81432',
    # hsx/jdk7u/hotspot wrong bugid
    'f5d8e6d72e23d972db522f7ad4cd3b9b01085466',
    # jdk8/tl/jdk erroneous push 7152892
    'da4b0962ad1161dbd84e7daa0fdc706281c456a2',
    # jdk8/tl/jdk/test/closed erroneous push 7152892
    '1e69a1ce212c7c4c884f155dd123c936787db273',
    # jdk9/jdk9/closed bad tag
    '61fdebb503d79392536b8f502ae215022d1a1f1c',
    ]

# Path to file containing additional blacklisted changesets
blacklist_file = '/oj/db/hg/blacklist'


# Checker class

class checker(object):

    def __init__(self, ui, repo, strict, lax):
        self.ui = ui
        self.repo = repo
        self.rv = Pass
        self.checks = [c for c in checker.__dict__ if c.startswith("c_")]
        self.checks.sort()
        self.summarized = False
        self.repo_bugids = [ ]
        self.cs_bugids = [ ]            # Bugids in current changeset
        self.cs_author = None           # Author of current changeset
        self.cs_reviewers = [ ]         # Reviewers of current changeset
        self.cs_contributor = None      # Contributor of current changeset
        self.strict = strict
        self.conf = load_conf(repo.root)
        self.whitespace_lax = lax and not strict
        if self.conf.get("whitespace") == "lax":
            self.whitespace_lax = True
        self.comments_lax = lax and not strict
        if self.conf.get("comments") == "lax":
            self.comments_lax = True
        self.tags_lax = lax and not strict
        if self.conf.get("tags") == "lax":
            self.tags_lax = True
        self.bugids_allow_dups = self.conf.get("bugids") == "dup"
        self.bugids_lax = lax and not strict
        if self.conf.get("bugids") == "lax":
            self.bugids_lax = True
        self.bugids_ignore = False
        if self.conf.get("bugids") == "ignore":
            self.bugids_ignore = True
        if not self.bugids_ignore:
            # only identify bug ids if we are going to use them
            self.repo_bugids = repo_bugids(ui, repo)
        self.blacklist = dict.fromkeys(changeset_blacklist)
        self.read_blacklist(blacklist_file)
        # hg < 1.0 does not have localrepo.tagtype()
        self.tagtype = getattr(self.repo, 'tagtype', lambda k: 'global')

    def read_blacklist(self, fname):
        if not os.path.exists(fname):
            return
        self.ui.debug('Reading blacklist file %s\n' % fname)
        f = open(fname)
        for line in f:
            # Any comment after the changeset hash becomes the dictionary value.
            l = [s.strip() for s in line.split('#', 1)]
            if l and l[0]:
                self.blacklist[l[0]] = len(l) == 2 and l[1] or None
        f.close()

    def summarize(self, ctx):
        self.ui.status("\n")
        self.ui.status("> Changeset: %d:%s\n" % (ctx.rev(), short(ctx.node())))
        self.ui.status("> Author:    %s\n" % ctx.user())
        self.ui.status("> Date:      %s\n" % datestr(ctx))
        self.ui.status(">\n> ")
        self.ui.status("\n> ".join(ctx.description().splitlines()))
        self.ui.status("\n\n")

    def error(self, ctx, msg):
        if self.rv != Fail:
            self.ui.status("[jcheck %s %s]\n" % (_version, _date))
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

        if ((ctx.rev() == 0 or (ctx.rev() == 1 and self.comments_lax))
            and ctx.user() == "duke"
            and ctx.description().startswith("Initial load")):
            return

        lns = ctx.description().splitlines()

        # If lax, filter out non-matching lines
        if self.comments_lax:
            lns = filter(checked_comment_line, lns)

        i = 0                           # Input index
        gi = -1                         # Grammar index
        n = 0                           # Occurrence count
        while i < len(lns):
            gi = gi + 1
            if gi >= len(comment_grammar):
                break
            ln = lns[i]
            st = comment_grammar[gi]
            n = 0
            while (st.ident_pattern.match(ln)):
                m = st.check_pattern.match(ln)
                if not m:
                    if not (st.name == "bugid line" and (self.bugids_lax or self.bugids_ignore)):
                        self.error(ctx, "Invalid %s" % st.name)
                elif st.validator:
                    if not (st.name == "bugid line" and self.bugids_ignore):
                        st.validator(self, ctx, m, self.conf["project"])
                n = n + 1
                i = i + 1
                if i >= len(lns):
                    break;
                ln = lns[i]
            if n < st.min and not self.comments_lax:
                self.error(ctx, "Incomplete comment: Missing %s" % st.name)
            if n > st.max:
                self.error(ctx, "Too many %ss" % st.name)

        if not self.cs_contributor and [self.cs_author] == self.cs_reviewers:
            self.error(ctx, "Self-reviews not permitted")
        if not self.comments_lax:
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
        if self.ui.debugflag:
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
            flags = fx.manifest().flags(f)
            if 'x' in flags:
                self.error(ctx, "%s: Executable files not permitted" % f)
            if 'l' in flags:
                self.error(ctx, "%s: Symbolic links not permitted" % f)

    def c_03_hash(self, ctx):
        hash = hex(ctx.node())
        if hash in self.blacklist:
            self.error(ctx, "Blacklisted changeset: " + hash)

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

        if not self.tags_lax:
            ts = self.repo.tags().keys()
            ignoredtypes = ['local']
            for t in ts:
                if not tag_re.match(t) and not self.tagtype(t) in ignoredtypes:
                    self.error(None,
                               "Illegal tag name: %s" % t)

        bs = self.repo.branchmap()
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
    repocompat(repo)
    if not repo.local():
        raise util.Abort("repository '%s' is not local" % repo.path)
    if not os.path.exists(os.path.join(repo.root, ".jcheck")):
        ui.note("jcheck not enabled (no .jcheck in repository root); skipping\n")
        return Pass
    strict = opts.has_key("strict") and opts["strict"]
    lax = opts.has_key("lax") and opts["lax"]
    if strict:
        lax = False
    ch = checker(ui, repo, strict, lax)
    ch.check_repo()
    firstnode = bin(node)
    start = repo.changelog.rev(firstnode)
    end = (hasattr(repo.changelog, 'count') and repo.changelog.count() or
           len(repo.changelog))
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
    repocompat(repo)
    if not repo.local():
        raise util.Abort("repository '%s' is not local" % repo.path)
    if not os.path.exists(os.path.join(repo.root, ".jcheck")):
        ui.status("jcheck not enabled (no .jcheck in repository root)\n")
        return Pass
    if len(opts["rev"]) == 0:
        opts["rev"] = ["tip"]

    strict = opts.has_key("strict") and opts["strict"]
    lax = opts.has_key("lax") and opts["lax"]
    if strict:
        lax = False
    ch = checker(ui, repo, strict, lax)
    ch.check_repo()

    try:
        nop = lambda c, fns: None
        iter = cmdutil.walkchangerevs(repo, _matchall(repo), opts, nop)
        for ctx in iter:
            ch.check(ctx.node())
    except (AttributeError, TypeError):
        # AttributeError:  matchall does not exist in hg < 1.1
        # TypeError:  walkchangerevs args differ in hg <= 1.3.1
        get = util.cachefunc(lambda r: repo.changectx(r).changeset())
        changeiter, matchfn = cmdutil.walkchangerevs(ui, repo, [], get, opts)
        if ui.debugflag:
            displayer = cmdutil.show_changeset(ui, repo, opts, True, matchfn)
        for st, rev, fns in changeiter:
            if st == 'add':
                node = repo.changelog.node(rev)
                if ui.debugflag:
                    displayer.show(rev, node, copies=False)
                ch.check(node)
            elif st == 'iter':
                if ui.debugflag:
                    displayer.flush(rev)

    if ch.rv == Fail:
        ui.status("\n")
    return ch.rv

opts = [("", "lax", False, "Check comments, tags and whitespace laxly"),
        ("r", "rev", [], "check the specified revision or range (default: tip)"),
        ("s", "strict", False, "check everything")]

help = "[-r rev] [-s]"

cmdtable = {
    "jcheck": (jcheck, opts, "hg jcheck " + help)
}
