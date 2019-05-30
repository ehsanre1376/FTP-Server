#!/usr/bin/env python
# coding: utf-8
from __future__ import print_function

import os
import threading

from .__init__ import *


class VFS(object):
    """single level in the virtual fs"""

    def __init__(self, realpath, vpath, uread=[], uwrite=[]):
        self.realpath = realpath  # absolute path on host filesystem
        self.vpath = vpath  # absolute path in the virtual filesystem
        self.uread = uread  # users who can read this
        self.uwrite = uwrite  # users who can write this
        self.nodes = {}  # child nodes

    def add(self, src, dst):
        """get existing, or add new path to the vfs"""
        assert not src.endswith("/")
        assert not dst.endswith("/")

        if "/" in dst:
            # requires breadth-first population (permissions trickle down)
            name, dst = dst.split("/", 1)
            if name in self.nodes:
                # exists; do not manipulate permissions
                return self.nodes[name].add(src, dst)

            vn = VFS(
                "{}/{}".format(self.realpath, name),
                "{}/{}".format(self.vpath, name).lstrip("/"),
                self.uread,
                self.uwrite,
            )
            self.nodes[name] = vn
            return vn.add(src, dst)

        if dst in self.nodes:
            # leaf exists; return as-is
            return self.nodes[dst]

        # leaf does not exist; create and keep permissions blank
        vp = "{}/{}".format(self.vpath, dst).lstrip("/")
        vn = VFS(src, vp)
        self.nodes[dst] = vn
        return vn

    def undot(self, path):
        ret = []
        for node in path.split("/"):
            if node in ["", "."]:
                continue

            if node == "..":
                if ret:
                    ret.pop()
                continue

            ret.append(node)

        return "/".join(ret)

    def _find(self, vpath):
        """return [vfs,remainder]"""
        vpath = self.undot(vpath)
        if vpath == "":
            return [self, ""]

        if "/" in vpath:
            name, rem = vpath.split("/", 1)
        else:
            name = vpath
            rem = ""

        if name in self.nodes:
            return self.nodes[name]._find(rem)

        return [self, vpath]

    def ls(self, vpath, user):
        """return user-readable [virt,real] items at vpath"""
        vn, rem = self._find(vpath)

        if user not in vn.uread:
            return [[], []]

        rp = vn.realpath
        if rem:
            rp += "/" + rem

        real = os.listdir(rp)
        real.sort()
        if rem:
            virt_vis = []
        else:
            virt_all = []  # all nodes that exist
            virt_vis = []  # nodes readable by user
            for name, vn2 in sorted(vn.nodes.items()):
                virt_all.append(name)
                if user in vn2.uread:
                    virt_vis.append(name)

            for name in virt_all:
                try:
                    real.remove(name)
                except:
                    pass

        absreal = []
        for p in real:
            absreal.append("{}/{}".format(rp, p).replace("//", "/"))

        return [absreal, virt_vis]


class AuthSrv(object):
    """verifies users against given paths"""

    def __init__(self, args, log_func):
        self.log_func = log_func
        self.args = args

        self.mutex = threading.Lock()
        self.reload()

    def log(self, msg):
        self.log_func("auth", msg)

    def invert(self, orig):
        if PY2:
            return {v: k for k, v in orig.iteritems()}
        else:
            return {v: k for k, v in orig.items()}

    def reload(self):
        """
        construct a flat list of mountpoints and usernames
        first from the commandline arguments
        then supplementing with config files
        before finally building the VFS
        """

        user = {}  # username:password
        mread = {}  # mountpoint:[username]
        mwrite = {}  # mountpoint:[username]
        mount = {}  # dst:src (mountpoint:realpath)

        if self.args.a:
            # list of username:password
            for u, p in [x.split(":", 1) for x in self.args.a]:
                user[u] = p

        if self.args.v:
            # list of src:dst:permset:permset:...
            # permset is [rwa]username
            for src, dst, perms in [x.split(":", 2) for x in self.args.v]:
                src = os.path.abspath(src)
                dst = dst.strip("/")
                mount[dst] = src
                mread[dst] = []
                mwrite[dst] = []

                perms = perms.split(":")
                for (lvl, uname) in [[x[0], x[1:]] for x in perms]:
                    if uname == "":
                        uname = "*"
                    if lvl in "ra":
                        mread[dst].append(uname)
                    if lvl in "wa":
                        mwrite[dst].append(uname)

        if self.args.c:
            for logfile in self.args.c:
                with open(logfile, "rb") as f:
                    for ln in [x.decode("utf-8").rstrip() for x in f]:
                        # self.log(ln)
                        pass

        # -h says our defaults are CWD at root and read/write for everyone
        vfs = VFS(os.path.abspath("."), "", ["*"], ["*"])

        maxdepth = 0
        for dst in sorted(mount.keys(), key=lambda x: (x.count("/"), len(x))):
            depth = dst.count("/")
            assert maxdepth <= depth
            maxdepth = depth

            if dst == "":
                # rootfs was mapped; fully replaces the default CWD vfs
                vfs = VFS(mount[dst], dst, mread[dst], mwrite[dst])
                continue

            v = vfs.add(mount[dst], dst)
            v.uread = mread[dst]
            v.uwrite = mwrite[dst]

        with self.mutex:
            self.vfs = vfs
            self.user = user
            self.iuser = self.invert(user)

        # import pprint
        # pprint.pprint({"usr": user, "rd": mread, "wr": mwrite, "mnt": mount})
