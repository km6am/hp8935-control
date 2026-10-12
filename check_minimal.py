#!/usr/bin/env python3
"""Checks for the minimal fork. Run it after touching anything in here.

  ~/miniconda3/envs/vnafit/bin/python check_minimal.py

Four checks, in the order they would catch a problem:

  1. The two .BAS files are byte-identical to the parent directory's. They are
     COPIES, not forks: the program that runs on the 8935 must be the same one
     the full tool loads, or a bug fixed in one place persists in the other
     and the version numbers stop meaning anything. Skipped with a note when
     the parent is not there, i.e. when this folder has been lifted out.
  2. link.PROG_VERSION matches the Ver$ in SINADCTL.BAS. The laptop names a
     version in exactly one place and the program in exactly one place; this
     is what keeps them from drifting. In SINADCTL 2.0-2.2 the PING case
     carried its own stale literal, so a correctly loaded program asked to be
     reloaded on every run - which teaches people to ignore the message that
     matters.
  3. Every --flag named in README.md or PROTOCOL.md exists, and every example
     command line in them parses. The parent's check_docs.py does this for the
     parent; the fork has its own options and its own docs, so it needs its
     own.
  4. The simulator smoke tests: load.py --sim and sinad.py measure --sim run
     to completion. These are the only end-to-end tests that exist here,
     because nobody may open the serial port.
"""
import os, re, shlex, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
BAS = ("SINADCTL.BAS", "SERLOAD.BAS")
DOCS = ("README.md", "PROTOCOL.md")
PY = sys.executable


def check_bas_identical():
    out, fails = [], []
    for name in BAS:
        mine = os.path.join(HERE, name)
        theirs = os.path.join(PARENT, name)
        if not os.path.exists(theirs):
            out.append(f"   {name}: parent copy not present, skipped "
                       f"(lifted-out folder)")
            continue
        a, b = open(mine, "rb").read(), open(theirs, "rb").read()
        if a == b:
            out.append(f"   {name}: identical to ../{name} ({len(a)} bytes)")
        else:
            fails.append(f"{name} has drifted from ../{name} - it must be a "
                         f"byte-identical copy. Fix with:  cp ../{name} "
                         f"{name}")
    return out, fails


def check_version():
    text = open(os.path.join(HERE, "SINADCTL.BAS")).read()
    lits = re.findall(r'Ver\$\s*=\s*"([0-9.]+)"', text)
    if len(lits) != 1:
        return [], [f"expected exactly one Ver$ in SINADCTL.BAS, found "
                    f"{len(lits)}"]
    stray = re.findall(r'OUTPUT Sp;"OK SINADCTL ([0-9]+\.[0-9]+)', text)
    fails = [f"a version literal outside Ver$ in SINADCTL.BAS: {s!r} - send "
             f"Ver$ instead, or PING and READY will drift apart" for s in stray]
    sys.path.insert(0, HERE)
    import link
    if link.PROG_VERSION != lits[0]:
        fails.append(f"link.PROG_VERSION is {link.PROG_VERSION} but "
                     f"SINADCTL.BAS Ver$ is {lits[0]}")
    return [f"   SINADCTL.BAS Ver$ = {lits[0]}, "
            f"link.PROG_VERSION = {link.PROG_VERSION}"], fails


def parsers():
    """The two programs' parsers, without running either of them."""
    sys.path.insert(0, HERE)
    import load as loadmod
    import sinad as sinadmod
    out = {"load.py": {"load.py": loadmod.build_parser()}}
    top = sinadmod.build_parser()
    subs = {"sinad.py": top}
    for act in top._actions:
        if hasattr(act, "choices") and isinstance(act.choices, dict):
            subs.update(act.choices)
    out["sinad.py"] = subs
    return out


def check_docs():
    import argparse, contextlib, io
    byprog = parsers()
    flags = {o for subs in byprog.values() for p in subs.values()
             for act in p._actions for o in act.option_strings
             if o.startswith("--") and o != "--help"}
    out, fails = [f"   {len(flags)} options across the two programs"], []
    for doc in DOCS:
        path = os.path.join(HERE, doc)
        if not os.path.exists(path):
            fails.append(f"{doc} is missing")
            continue
        text = open(path).read()
        named = set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]+", text))
        bogus = sorted(named - flags - {"--help"})
        if bogus:
            fails += [f"{doc} names an option that does not exist: {b}"
                      for b in bogus]
        n = bad = 0
        for line in text.splitlines():
            line = re.sub(r"\s+#.*$", "", line.strip()).lstrip("$ ")
            m = re.match(r"(?:\S*/)?python3?\s+(load|sinad)\.py\b(.*)$", line)
            if not m:
                continue
            script, rest = m.group(1) + ".py", m.group(2)
            if re.match(r"\s{2,}", rest):      # a description column
                continue
            args = [x for x in shlex.split(rest.strip()) if x != "..."]
            subs = byprog[script]
            parser = subs.get(args[0] if args else "", subs[script])
            rest_args = args[1:] if (args and args[0] in subs) else args
            n += 1
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    parser.parse_args(rest_args)
            except SystemExit:
                bad += 1
                fails.append(f"{doc} example does not parse: "
                             f"{script} {' '.join(args)}")
        out.append(f"   {doc}: {len(named)} options named, {n} examples, "
                   f"{bad} failing")
    return out, fails


def check_sim():
    out, fails = [], []
    for args, want in (
            (["load.py", "--sim"], "READY"),
            (["sinad.py", "measure", "--sim"], "dB SINAD at"),
            (["sinad.py", "ping", "--sim"], "SINADCTL running")):
        r = subprocess.run([PY] + args, cwd=HERE, capture_output=True,
                           text=True, timeout=300)
        label = " ".join(args)
        if r.returncode != 0:
            fails.append(f"{label} exited {r.returncode}: "
                         f"{(r.stderr or r.stdout).strip()[-300:]}")
        elif want not in r.stdout:
            fails.append(f"{label} did not print {want!r}")
        else:
            out.append(f"   {label}: ok")
    return out, fails


def main():
    fails = []
    for n, (title, fn) in enumerate((
            ("the .BAS copies are byte-identical to the parent's",
             check_bas_identical),
            ("the version lives in one place on each side", check_version),
            ("the docs match the options", check_docs),
            ("the simulator runs end to end", check_sim)), 1):
        out, bad = fn()
        print(f"{n}. {title}")
        for line in out:
            print(line)
        fails += bad
    print()
    if fails:
        print(f"{len(fails)} problem(s):")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("minimal/ is consistent with itself and with the parent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
