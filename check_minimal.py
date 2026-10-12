#!/usr/bin/env python3
"""Checks that need no instrument. Run it after changing anything here.

  python3 check_minimal.py

Four checks, in the order they would catch a problem:

  1. SINADCTL.BAS and SERLOAD.BAS byte-compared against reference copies one
     directory up, when any are there. An integrity check for a checkout that
     has them; with none present it says so and moves on, and the other three
     checks still run.
  2. link.PROG_VERSION matches the Ver$ literal in SINADCTL.BAS, and no
     second version literal exists anywhere in the program. The version in
     the READY line is the only way to tell from the laptop that a load
     actually took, so each side names it in exactly one place. Releases
     2.0-2.2 carried two copies of the number, they drifted, and a correctly
     loaded program then asked to be reloaded on every run.
  3. Every option named in README.md or PROTOCOL.md exists, and every example
     command line in them parses. Those documents have no other way of being
     told they have gone stale.
  4. The simulator smoke tests: load.py --sim and sinad.py measure --sim run
     to completion. These are the only end-to-end tests here, since the real
     ones need an instrument.
"""
import os, re, shlex, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ABOVE = os.path.dirname(HERE)   # where a reference copy may sit
BAS = ("SINADCTL.BAS", "SERLOAD.BAS")
DOCS = ("README.md", "PROTOCOL.md")
PY = sys.executable


def check_bas_identical():
    """Compare the two .BAS files with reference copies one directory up.

    Absence of a reference copy is not a failure: a standalone checkout has
    none, and the files here are the originals as far as it is concerned. It
    is reported rather than passed over silently, so that a checkout which was
    MEANT to have one does not quietly stop being checked."""
    out, fails, found = [], [], 0
    for name in BAS:
        mine = os.path.join(HERE, name)
        if not os.path.exists(mine):
            fails.append(f"{name} is missing")
            continue
        ref = os.path.join(ABOVE, name)
        if not os.path.exists(ref):
            continue
        found += 1
        a, b = open(mine, "rb").read(), open(ref, "rb").read()
        if a == b:
            out.append(f"   {name}: identical to the copy above "
                       f"({len(a)} bytes)")
        else:
            fails.append(f"{name} differs from the copy one directory up; "
                         f"they are meant to be byte-identical")
    if not found:
        out.append("   no reference copies one directory up: nothing to "
                   "compare, skipped")
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
    """Run each program against the simulator and look for its headline line.

    The load goes at --stream-delay 0 rather than the default 0.08. Two
    reasons. The delay is a hardware timing constant - the 8935's command bar
    drops characters at full line rate - and a simulator cannot say anything
    about whether its value is right, so running the default proves nothing.
    And at 0.08 a 732-line stream takes a minute, during which the simulator
    applies SERLOAD's real rule that five seconds of silence ends the stream:
    on a loaded machine the scheduler can produce that gap, the stream is
    reported short, and the check fails for a reason that has nothing to do
    with the code. (That the failure is *reported* rather than silently
    stored is the loader behaving correctly; see load.py.)"""
    out, fails = [], []
    for args, want in (
            (["load.py", "--sim", "--stream-delay", "0"], "READY"),
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
            ("the IBASIC sources match any reference copy",
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
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
