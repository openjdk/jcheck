#
# Copyright (c) 2007, 2018, Oracle and/or its affiliates. All rights reserved.
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
from mercurial import cmdutil, context, error, patch, templater, util, utils
try:
    # Mercurial 4.3 and higher
    from mercurial import registrar
except ImportError:
    registrar = {}
    pass

# Abort() was moved/copied from util to error in hg 1.3 and was removed from
# util in 4.6.
error_Abort = None
if hasattr(error, 'Abort'):
    error_Abort = error.Abort
else:
    error_Abort = util.Abort

# date-related utils moved to utils/dateutil in early 2018 (hg 4.7)
dateutil_datestr = None
if hasattr(utils, 'dateutil'):
    dateutil_datestr = utils.dateutil.datestr
else:
    dateutil_datestr = util.datestr

Pass = False
Fail = True

def datestr(ctx):
    # Mercurial 0.9.5 and earlier append a time zone; strip it.
    return dateutil_datestr(ctx.date(), format="%Y-%m-%d %H:%M")[:16]

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
                raise error_Abort("%s:%d: Invalid configuration syntax: %s"
                                 % (fn, i, ln))
            cf[m.group(1)] = m.group(2)
    finally:
        f.close()
    for pn in ["project"]:
        if not cf.has_key(pn):
            raise error_Abort("%s: Missing property: %s" % (fn, pn))
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
tag_re = re.compile("tip$|jdk-([1-9]([0-9]*)(\.(0|[1-9][0-9]*)){0,3})(\+(([0-9]+))|(-ga))$|jdk[4-9](u\d{1,3})?-((b\d{2,3})|(ga))$|hs\d\d(\.\d{1,2})?-b\d\d$")

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
    '931e5f39e365a0d550d79148ff87a7f9e864d2e1', # hotspot dup bugid 7147064
    'd8abc90163a4b58db407a60cba331ab21c9977e7', # hotspot dup bugid 7147064
    '45849c62c298aa8426c9e67599e4e35793d8db13', # pubs executable files
    '38050e6655d8acc220800a28128cef328906e825', # pubs invalid bugid line
    # hotspot/test/closed no Reviewed-by line
    '8407fef5685f32ed42b79c5d5f13f6c8007171ac',
    'c667bae72ea8530ef1e055dc25951b991dfd5888', # hotspot dup bugid 8169597 (hs)
    '5a574ef5a4eec3ec3be9352aae3b383202c9a3a6', # hotspot dup bugid 8169597 (dev)
    '38a240fd58a287acb1963920b92ed4d9c2fd39e3', # hotspot dup bugid 8179954 (jdk10)
    'fc8c54b03f821dbc7385ab6b08cb91cc7a3bf3cb', # hotspot dup bugid 8179954 (hs)
    # For duplicate bugids, add the hashes of all related changesets!

    # consolidated/open
    '489c9b5090e2bdfe3a2f196afe013025e7443f6b',
    '90ce3da70b431eab8f123abd25ceda9e53a094a9',
    '02bb8761fcce2922d1619062a303dbce266068a9',
    '01d07c8452ff8e96f3ff777f0b50e1c98774b9df',
    '7f561c08de6b09951cf79975dba08150982c7bb3',
    'af5240695a6de2c89f01e6de58e9bad6f582c9ff',
    '474761f14bcad3a18b5e6990447402c3a24d5fea',
    'aa192ed8538b76aa647e9cdd89e485b5f10e0a26',
    '06bc494ca11ef44070b1ea054c34c3655c93ddb2',
    '1cc8dd79fd1cd13d36b385196271a29632c67c3b',
    '408b55da75b0ae21ce9f6f27a798d051d4675e4e',
    '74fe6922716dbd4e10b5d5efbf23af551b84a697',
    '51a7bc3e93a011c733f83ab871612ccdc6216a75',
    '5b0720709093938bc2e0d6e4522059d893462738',
    '05173e59b8785ba423d0a582d06957596dce193d',
    '80e13954d5b063a2275778e96e639b4282861610',
    '4e9d88727ae307a6430931dad8e569bc0bf465c4',
    'e14008f86acd1d3860aa4cce7d5fe62c70529d48',
    'abae672ab077e142e228067a63490868da536c60',
    '898f519b613889dbce3c16c2baf482d1f4243f8e',
    '7e19cecfbfc8bf88b52fc88758817f780bf188a1',
    '3b2c9223cdf512ba11c7db61f196a187d82d0036',
    '370f960bd6dbf4cd670625eab08364a190f9afc3',
    '564d8dc66b61329bbe2576a93b68d41d3ccdba00',
    '249e283e044665a83dbce8e75a97bf63f83cb102',
    '3d179532574942423bcb9fbdf4c7afe003ccceeb',
    '71e33d83609b052fc9490b1822829ca692662d71',
    '862a85ed20dbdf0efc1539cc83aff7dff60194ef',
    '14672d061f7a42801f3feab49228f36272ded78a',
    '0d803d2ebd6b4544145331fb7f2e4c0eb0f0ad64',
    '59439733e87a34e9b41bd003c3ab7580112fc4f3',
    'e12adc424b4309163099c518e771c7eb159f94a4',
    '11c76613f3a2143d253fb3c389119f41188d709d',
    'bbe9212c700515be4c8c5dff0354104386810e8c',
    'f0e156a39c75441522f05bc7abc2675a37ea0b1c',
    'd1f02d5e4c740acc0b2b5651126f38090a556171',
    '7b3eaf04308f28aac3d21e05e8487df9d29719a4',
    '011727a60840e202a9c556d840636e3907fd0ce1',
    '425e2c6b5941e31797c6feca184ecfbd7c1c077b',
    '0f8aea9a422ed9a888623e0f918cfc71be8a5a24',
    'a8ab83cbaa49a9232ed8153d731bc9e328f6ee61',

    # consolidated/closed
    'e7e6bffe1f8028ba4daf575385dc4fd578034d2f',
    '2523cc85defa8d570b0b211c38f2b08fc457eb6c',
    '47c62354c6da8cd5022d92babafc269878a9340f',
    '01a573cdd8d0a26a851dffdf126f96fbd829ac6e',
    '26373189d6f8f9f6eed4d9a6ac2345cc75388a80',
    'ca94fe25e6a503e9641c482b5d76c4d55b0ac297',
    'a89ff61916e503648783883124f60a459e25df1f',
    'f41443d20e3bdca9a16b94a7a464cb7ac9b2ca73',
    '0e2c107c7319e4bbdc8ee80c4dba3d87329ee19f',
    '06905d1339554298cecfa9d599e6fbaefbcd8df7',
    '324534d86a9cad44404dcfcff5e45a21d91eb445',
    'd4c8044fa522ae5e89215324f7035e0ec9f8df55',
    '76ec26e0c56712624e6a5809929571a5bd028576',
    '38557f4c06fdc2209ede8044dd7bd6893ea365f4',
    '015b1a27f5352eb24ad975b1a9f45a1d62d4e977',
    'dfae63c29a6cc3254097065c629d85dac5d10c81',
    '87a0ce109f0f1de36e4520cfd020926b2b4a2cbc',
    '5bc60aea1e1634843c79f5426d8f682a37e2092f',
    '199381c054109f57ffcd2291fa343c528b53b6d9',
    '22f717ecdcce500190b685763bcddc68d55d3316',
    'ece95c3640926c371c885358ab6b54e18579e3e2',
    '2c88ed83131005533c9a43d5da1f5fd7ff5675d8',
    '38835cfd0829bd91cfbe5a94ff761c92004cdd07',
    '3782924e5ad1e331fa221a4f37d2cabe9b3734fb',
    '70ff4a44bcf94be3b4bdfb9189e70e2d08aaf8c0',
    'd999bdc2f2bea8761b6b430115e84c18d4fcf6a4',
    '2d8b9e27c05ed338badf0bb82b1f22fa13c0a2d2',
    '667bbf13b1bf6b50074fa80240cea77c2c0b21ba',
    '94deb45ef34f9dab46d8401d51ce446d072f4917',
    '58e382f36a016ed31b71544256139fdd10a405c3',
    'd5b7c3f4f5220ae0e927501ae53e43652668b5ae',
    '443167e10bc4eed20301adef5121af9394e844e3',
    '8b1f7ef1cd682b16d5f41b34c5d474adf2cf11ab',
    '9fd855244664fa1ba553bc823a6e8fed1183ad32',
    '5e64c143b0c6163ac815ea159fa8c11b57ccc445',
    '6a8e2a080676822e67f9b0d51943c8110ec861b0',
    '4ce78429449f8100ccb289b51d63b055cec37223',
    'e46a0e002a57095855bb632edb447597cf6cecf7',
    '7cb53066e470c26002191263a664350034d49bff',
    '840eac30564f5304dbaaec276a2dabf353c7f623',
    'fd67174f8a7708238c84896603a960ea9b5e3cca',

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
    # jdk9/hs-rt/jdk/src/closed dup bugid 8034951
    'a19596796430761dde87bee9f6616480f1c93678',
    # jdk9/hs-rt/jdk/test/closed dup bugid 8034951
    'd2308c9714c94e87a0e60cda314746a5c17dbcc2',
    # jdk9/client/deploy erroneous push 8041798
    'fff4ff4fd6f031ab335b44842d69fd125297b5ab',
    # jdk/jdk10 (closed) erroneous restoration of tests 8194908
    '050a07d47f72c341bb6cb47a85ea729791c9f350',
    # jdk-updates/jdk10u-cpu (closed) erroneous restoration of tests 8194916
    '92419449b854803e7b5f3f4b89dfcf6fd564aeef',
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
                if "\t" in data or "\r" in data or " \n" in data:
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
        raise error_Abort("repository '%s' is not local" % repo.path)
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

# From Mercurial 1.9, the preferred way to define commands is using the @command
# decorator. If this isn't available, fallback on a simple local implementation
# that just adds the data to the cmdtable.
cmdtable = {}
if hasattr(registrar, 'command'):
    command = registrar.command(cmdtable)
elif hasattr(cmdutil, 'command'):
    command = cmdutil.command(cmdtable)
else:
    def command(name, options, synopsis):
        def decorator(func):
            cmdtable[name] = func, list(options), synopsis
            return func
        return decorator

opts = [("", "lax", False, "Check comments, tags and whitespace laxly"),
        ("r", "rev", [], "check the specified revision or range (default: tip)"),
        ("s", "strict", False, "check everything")]

help = "[-r rev] [-s]"

@command("jcheck", opts, "hg jcheck " + help)
def jcheck(ui, repo, **opts):
    """check changesets against JDK standards"""
    ui.debug("jcheck repo=%s opts=%s\n" % (repo.path, opts))
    repocompat(repo)
    if not repo.local():
        raise error_Abort("repository '%s' is not local" % repo.path)
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

# This is invoked on servers to check pushkeys; it's not needed on clients.
def prepushkey(ui, repo, hooktype, namespace, key, old=None, new=None, **opts):
    if namespace == 'phases':
        return Pass
    ui.write_err('ERROR:  pushing keys (%s) is disabled\n' % namespace)
    return Fail
