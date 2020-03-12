#
# Copyright 2008, 2017, Sun Microsystems, Inc.  All Rights Reserved.
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

# Pseudo-extension for running jcheck unit tests
# that require extraordinary configuration

import sys, os, re, urllib, urllib2
from mercurial.node import *
from mercurial import cmdutil, patch, util, context, templater
try:
    # Mercurial 4.3 and higher
    from mercurial import registrar
except ImportError:
    registrar = {}
    pass

# Extend the path so that we can import the jcheck extension itself
sys.path.insert(0, os.path.dirname(__file__))
import jcheck

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

opts = (jcheck.opts +
       [("", "white", [], "changeset hash for whitelist (TESTING)"),
        ("", "black", [], "changeset hash for blacklist (TESTING)")])

help = "[--white hash] [--black hash] " + jcheck.help

@command("jcheck_test", opts, "hg jcheck_test " + help)
def jcheck_test(ui, repo, **opts):
    """check changesets against JDK standards (TESTING)"""
    ui.debug("jcheck repo=%s opts=%s\n" % (repo.path, opts))
    if len(opts["white"]) != 0:
        jcheck.changeset_whitelist = opts["white"]
    if len(opts["black"]) != 0:
        jcheck.changeset_blacklist = opts["black"]
    jcheck.blacklist_file = "./blacklist"
    del opts["white"]
    del opts["black"]
    return jcheck.jcheck(ui, repo, **opts)
