#!/usr/bin/env python3

import os
import sys
import time
import shutil
import sqlite3
import argparse

DB_VER1 = 3
DB_VER2 = 4


def die(msg):
    print("\033[31m\n" + msg + "\n\033[0m")
    sys.exit(1)


def read_ver(db):
    for tab in ["ki", "kv"]:
        try:
            c = db.execute(r"select v from {} where k = 'sver'".format(tab))
        except:
            continue

        rows = c.fetchall()
        if rows:
            return int(rows[0][0])

    return "corrupt"


def ls(db):
    nfiles = next(db.execute("select count(w) from up"))[0]
    ntags = next(db.execute("select count(w) from mt"))[0]
    print(f"{nfiles} files")
    print(f"{ntags} tags\n")

    print("number of occurences for each tag,")
    print(" 'x' = file has no tags")
    print(" 't:mtp' = the mtp flag (file not mtp processed yet)")
    print()
    for k, nk in db.execute("select k, count(k) from mt group by k order by k"):
        print(f"{nk:9} {k}")


def compare(n1, d1, n2, d2, verbose):
    nt = next(d1.execute("select count(w) from up"))[0]
    n = 0
    miss = 0
    for w1, rd, fn in d1.execute("select w, rd, fn from up"):
        n += 1
        if n % 25_000 == 0:
            m = f"\033[36mchecked {n:,} of {nt:,} files in {n1} against {n2}\033[0m"
            print(m)

        if rd.split("/", 1)[0] == ".hist":
            continue

        q = "select w from up where rd = ? and fn = ?"
        hit = d2.execute(q, (rd, fn)).fetchone()
        if not hit:
            miss += 1
            if verbose:
                print(f"file in {n1} missing in {n2}: [{w1}] {rd}/{fn}")

    print(f" {miss} files in {n1} missing in {n2}\n")

    nt = next(d1.execute("select count(w) from mt"))[0]
    n = 0
    miss = {}
    nmiss = 0
    for w1, k, v in d1.execute("select * from mt"):

        n += 1
        if n % 100_000 == 0:
            m = f"\033[36mchecked {n:,} of {nt:,} tags in {n1} against {n2}, so far {nmiss} missing tags\033[0m"
            print(m)

        q = "select rd, fn from up where substr(w,1,16) = ?"
        rd, fn = d1.execute(q, (w1,)).fetchone()
        if rd.split("/", 1)[0] == ".hist":
            continue

        q = "select substr(w,1,16) from up where rd = ? and fn = ?"
        w2 = d2.execute(q, (rd, fn)).fetchone()
        if w2:
            w2 = w2[0]

        v2 = None
        if w2:
            v2 = d2.execute(
                "select v from mt where w = ? and +k = ?", (w2, k)
            ).fetchone()
            if v2:
                v2 = v2[0]

        # if v != v2 and v2 and k in [".bpm", "key"] and n2 == "src":
        #    print(f"{w} [{rd}/{fn}] {k} = [{v}] / [{v2}]")

        if v2 is not None:
            if k.startswith("."):
                try:
                    diff = abs(float(v) - float(v2))
                    if diff > float(v) / 0.9:
                        v2 = None
                    else:
                        v2 = v
                except:
                    pass

            if v != v2:
                v2 = None

        if v2 is None:
            nmiss += 1
            try:
                miss[k] += 1
            except:
                miss[k] = 1

            if verbose:
                print(f"missing in {n2}: [{w1}] [{rd}/{fn}] {k} = {v}")

    for k, v in sorted(miss.items()):
        if v:
            print(f"{n1} has {v:6} more {k:<6} tags than {n2}")

    print(f"in total, {nmiss} missing tags in {n2}\n")


def copy_mtp(d1, d2, tag, rm):
    nt = next(d1.execute("select count(w) from mt where k = ?", (tag,)))[0]
    n = 0
    ndone = 0
    for w1, k, v in d1.execute("select * from mt where k = ?", (tag,)):
        n += 1
        if n % 25_000 == 0:
            m = f"\033[36m{n:,} of {nt:,} tags checked, so far {ndone} copied\033[0m"
            print(m)

        q = "select rd, fn from up where substr(w,1,16) = ?"
        rd, fn = d1.execute(q, (w1,)).fetchone()
        if rd.split("/", 1)[0] == ".hist":
            continue

        q = "select substr(w,1,16) from up where rd = ? and fn = ?"
        w2 = d2.execute(q, (rd, fn)).fetchone()
        if not w2:
            continue

        w2 = w2[0]
        hit = d2.execute("select v from mt where w = ? and +k = ?", (w2, k)).fetchone()
        if hit:
            hit = hit[0]

        if hit != v:
            ndone += 1
            if hit is not None:
                d2.execute("delete from mt where w = ? and +k = ?", (w2, k))

            d2.execute("insert into mt values (?,?,?)", (w2, k, v))
            if rm:
                d2.execute("delete from mt where w = ? and +k = 't:mtp'", (w2,))

    d2.commit()
    print(f"copied {ndone} {tag} tags over")


def main():
    os.system("")
    print()

    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="database to work on")
    ap.add_argument("-src", metavar="DB", type=str, help="database to copy from")

    ap2 = ap.add_argument_group("informational / read-only stuff")
    ap2.add_argument("-v", action="store_true", help="verbose")
    ap2.add_argument("-ls", action="store_true", help="list summary for db")
    ap2.add_argument("-cmp", action="store_true", help="compare databases")

    ap2 = ap.add_argument_group("options which modify target db")
    ap2.add_argument("-copy", metavar="TAG", type=str, help="mtp tag to copy over")
    ap2.add_argument(
        "-rm-mtp-flag",
        action="store_true",
        help="when an mtp tag is copied over, also mark that as done, so copyparty won't run mtp on it",
    )
    ap2.add_argument("-vac", action="store_true", help="optimize DB")

    ar = ap.parse_args()

    for v in [ar.db, ar.src]:
        if v and not os.path.exists(v):
            die("database must exist")

    db = sqlite3.connect(ar.db)
    ds = sqlite3.connect(ar.src) if ar.src else None

    # revert journals
    for d, p in [[db, ar.db], [ds, ar.src]]:
        if not d:
            continue

        pj = "{}-journal".format(p)
        if not os.path.exists(pj):
            continue

        d.execute("create table foo (bar int)")
        d.execute("drop table foo")

    if ar.copy:
        db.close()
        shutil.copy2(ar.db, "{}.bak.dbtool.{:x}".format(ar.db, int(time.time())))
        db = sqlite3.connect(ar.db)

    for d, n in [[ds, "src"], [db, "dst"]]:
        if not d:
            continue

        ver = read_ver(d)
        if ver == "corrupt":
            die("{} database appears to be corrupt, sorry")

        if ver < DB_VER1 or ver > DB_VER2:
            m = f"{n} db is version {ver}, this tool only supports versions between {DB_VER1} and {DB_VER2}, please upgrade it with copyparty first"
            die(m)

    if ar.ls:
        ls(db)

    if ar.cmp:
        if not ds:
            die("need src db to compare against")

        compare("src", ds, "dst", db, ar.v)
        compare("dst", db, "src", ds, ar.v)

    if ar.copy:
        copy_mtp(ds, db, ar.copy, ar.rm_mtp_flag)


if __name__ == "__main__":
    main()
