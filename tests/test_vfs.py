#!/usr/bin/env python
# coding: utf-8
from __future__ import print_function

import os
import json
import shutil
import unittest

from argparse import Namespace
from copyparty.authsrv import *


class TestVFS(unittest.TestCase):
    def dump(self, vfs):
        print(json.dumps(vfs, indent=4, sort_keys=True, default=lambda o: o.__dict__))

    def unfoo(self, foo):
        for k, v in {"foo": "a", "bar": "b", "baz": "c", "qux": "d"}.items():
            foo = foo.replace(k, v)

        return foo

    def undot(self, vfs, query, response):
        self.assertEqual(vfs.undot(query), response)
        query = self.unfoo(query)
        response = self.unfoo(response)
        self.assertEqual(vfs.undot(query), response)

    def absify(self, root, names):
        return ["{}/{}".format(root, x).replace("//", "/") for x in names]

    def test(self):
        td = "/dev/shm/vfs"
        try:
            shutil.rmtree(td)
        except:
            pass

        os.mkdir(td)
        os.chdir(td)

        for a in "abc":
            for b in "abc":
                for c in "abc":
                    folder = "{0}/{0}{1}/{0}{1}{2}".format(a, b, c)
                    os.makedirs(folder)
                    for d in "abc":
                        fn = "{}/{}{}{}{}".format(folder, a, b, c, d)
                        with open(fn, "w") as f:
                            f.write(fn)

        # defaults
        vfs = AuthSrv(Namespace(c=None, a=[], v=[]), None).vfs
        self.assertEqual(vfs.nodes, {})
        self.assertEqual(vfs.vpath, "")
        self.assertEqual(vfs.realpath, td)
        self.assertEqual(vfs.uread, ["*"])
        self.assertEqual(vfs.uwrite, ["*"])

        # single read-only rootfs (relative path)
        vfs = AuthSrv(Namespace(c=None, a=[], v=["a/ab/::r"]), None).vfs
        self.assertEqual(vfs.nodes, {})
        self.assertEqual(vfs.vpath, "")
        self.assertEqual(vfs.realpath, td + "/a/ab")
        self.assertEqual(vfs.uread, ["*"])
        self.assertEqual(vfs.uwrite, [])

        # single read-only rootfs (absolute path)
        vfs = AuthSrv(Namespace(c=None, a=[], v=[td + "//a/ac/../aa//::r"]), None).vfs
        self.assertEqual(vfs.nodes, {})
        self.assertEqual(vfs.vpath, "")
        self.assertEqual(vfs.realpath, td + "/a/aa")
        self.assertEqual(vfs.uread, ["*"])
        self.assertEqual(vfs.uwrite, [])

        # read-only rootfs with write-only subdirectory (read-write for k)
        vfs = AuthSrv(
            Namespace(c=None, a=["k:k"], v=[".::r:ak", "a/ac/acb:a/ac/acb:w:ak"]), None
        ).vfs
        self.assertEqual(len(vfs.nodes), 1)
        self.assertEqual(vfs.vpath, "")
        self.assertEqual(vfs.realpath, td)
        self.assertEqual(vfs.uread, ["*", "k"])
        self.assertEqual(vfs.uwrite, ["k"])
        n = vfs.nodes["a"]
        self.assertEqual(len(vfs.nodes), 1)
        self.assertEqual(n.vpath, "a")
        self.assertEqual(n.realpath, td + "/a")
        self.assertEqual(n.uread, ["*", "k"])
        self.assertEqual(n.uwrite, ["k"])
        n = n.nodes["ac"]
        self.assertEqual(len(vfs.nodes), 1)
        self.assertEqual(n.vpath, "a/ac")
        self.assertEqual(n.realpath, td + "/a/ac")
        self.assertEqual(n.uread, ["*", "k"])
        self.assertEqual(n.uwrite, ["k"])
        n = n.nodes["acb"]
        self.assertEqual(n.nodes, {})
        self.assertEqual(n.vpath, "a/ac/acb")
        self.assertEqual(n.realpath, td + "/a/ac/acb")
        self.assertEqual(n.uread, ["k"])
        self.assertEqual(n.uwrite, ["*", "k"])

        real, virt = vfs.ls("/", "*")
        self.assertEqual(real, self.absify(td, ["b", "c"]))
        self.assertEqual(virt, ["a"])

        real, virt = vfs.ls("a", "*")
        self.assertEqual(real, self.absify(td, ["a/aa", "a/ab"]))
        self.assertEqual(virt, ["ac"])

        real, virt = vfs.ls("a/ab", "*")
        self.assertEqual(real, self.absify(td, ["a/ab/aba", "a/ab/abb", "a/ab/abc"]))
        self.assertEqual(virt, [])

        real, virt = vfs.ls("a/ac", "*")
        self.assertEqual(real, self.absify(td, ["a/ac/aca", "a/ac/acc"]))
        self.assertEqual(virt, [])

        real, virt = vfs.ls("a/ac", "k")
        self.assertEqual(real, self.absify(td, ["a/ac/aca", "a/ac/acc"]))
        self.assertEqual(virt, ["acb"])

        real, virt = vfs.ls("a/ac/acb", "*")
        self.assertEqual(real, [])
        self.assertEqual(virt, [])

        real, virt = vfs.ls("a/ac/acb", "k")
        self.assertEqual(
            real, self.absify(td, ["a/ac/acb/acba", "a/ac/acb/acbb", "a/ac/acb/acbc"])
        )
        self.assertEqual(virt, [])

        # breadth-first construction
        vfs = AuthSrv(
            Namespace(
                c=None,
                a=[],
                v=[
                    "a/ac/acb:a/ac/acb:w",
                    "a:a:w",
                    ".::r",
                    "abacdfasdq:abacdfasdq:w",
                    "a/ac:a/ac:w",
                ],
            ),
            None,
        ).vfs

        # sanitizing relative paths
        self.undot(vfs, "foo/bar/../baz/qux", "foo/baz/qux")
        self.undot(vfs, "foo/../bar", "bar")
        self.undot(vfs, "foo/../../bar", "bar")
        self.undot(vfs, "foo/../../", "")
        self.undot(vfs, "./.././foo/", "foo")
        self.undot(vfs, "./.././foo/..", "")

        # shadowing
        vfs = AuthSrv(Namespace(c=None, a=[], v=[".::r", "b:a/ac:r"]), None).vfs

        r1, v1 = vfs.ls("", "*")
        self.assertEqual(r1, self.absify(td, ["b", "c"]))
        self.assertEqual(v1, ["a"])

        r1, v1 = vfs.ls("a", "*")
        self.assertEqual(r1, self.absify(td, ["a/aa", "a/ab"]))
        self.assertEqual(v1, ["ac"])

        r1, v1 = vfs.ls("a/ac", "*")
        r2, v2 = vfs.ls("b", "*")
        self.assertEqual(r1, self.absify(td, ["b/ba", "b/bb", "b/bc"]))
        self.assertEqual(r1, r2)
        self.assertEqual(v1, v2)

        shutil.rmtree(td)
