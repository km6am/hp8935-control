#!/usr/bin/env python3
"""
load.py - get SINADCTL.BAS onto an HP 8935 over RS-232 and run it.

  python3 load.py              type the loader, stream the program, store, run
  python3 load.py --start      skip loading: LOAD the stored copy and RUN it
  python3 load.py --direct     type every program line onto the command bar

--start is what you want day to day: a few seconds against a minute and a
half, because the 8935's RAM disc is battery-backed and the stored program
survives a power cycle.

Before the first load, on the 8935: I/O CONFIGURE with Serial In = Inst,
IBASIC Echo = On, 9600, None, 8, 1, Rcv/Xmt Pace = None; then show the TESTS
(IBASIC CONTROLLER) screen and put the cursor on the command bar - the
highlighted strip at top left. SINADCTL switches Serial In to IBASIC itself
when it runs, and back on QUIT.

Add --sim to try the whole thing with no hardware.  Requires pyserial.
Protocol and the reasoning behind each step: PROTOCOL.md.
"""
import argparse, math, os, re, sys, time

from link import (BAR, Progress, check_version, clear_bar, connection_args,
                  open_link, require_state)


def program_lines(path, keep_comments=False, start=10, step=10):
    """Read a .BAS file. Numbered lines keep their numbers; unnumbered lines
    are numbered from `start`. Blank lines, and comment-only lines unless
    keep_comments, are dropped - they cost ~2 s each typed and 0.08 s each
    streamed, and SINADCTL is mostly comments."""
    out, n = [], start
    for raw in open(path, encoding="ascii", errors="replace"):
        m = re.match(r"\s*(\d+)\s?(.*)$", raw.rstrip("\r\n"))
        num, body = (int(m.group(1)), m.group(2)) if m else (None, raw.rstrip("\r\n"))
        if body.strip() == "" or (not keep_comments and body.strip().startswith("!")):
            if num is not None:
                n = num + step
            continue
        if num is None:
            num, n = n, n + step
        else:
            n = num + step
        out.append(f"{num} {body}")
    return out


def _send_one(link, ln, a, delay):
    """Type one line and collect the echo until it goes quiet."""
    link.write_line(ln, a.eol, delay)
    echo, first = [], None
    end = time.time() + a.line_timeout
    last = time.time()
    while time.time() < end:
        r = link.readline(0.05)
        if r is not None:
            echo.append(r)
            last = time.time()
            first = first or last
        elif first and time.time() - last > 0.4:
            break
    if not first:
        time.sleep(max(0.0, 2.0 - a.line_timeout))
    replies = [e for e in echo if e.strip("\r\n\x00 \t")
               and e.strip("\r\n\x00 \t") != ln.strip()]
    return echo, " | ".join(replies)


def type_lines(link, lines, a, label="program"):
    """Type lines onto the IBASIC command bar, one at a time, waiting for each
    echo to go quiet. Returns [(line, error_text)].

    The echo is checked, not just scanned for ERROR: the bar echoes exactly
    what it received, so an echo that does not match means characters were
    dropped on the way in. That used to pass silently - the mismatch matched
    no ERROR pattern, so a corrupted program loaded reporting no errors."""
    errors = []
    bar = Progress(label, len(lines))
    delay = a.char_delay
    for i, ln in enumerate(lines, 1):
        for attempt in (1, 2, 3):
            echo, text = _send_one(link, ln, a, delay)
            if re.search(r"\bERROR\s+\d+|Improper|Syntax error", text, re.I):
                errors.append((ln, text))
                print(f"\n  !! {ln}\n     {text}")
                break
            if any(e.strip("\r\n\x00 \t") == ln.strip() for e in echo):
                break
            if attempt < 3:
                link.write_line("\x08" * (len(ln) + 4), "", max(delay, 0.005))
                time.sleep(0.2)
                link.read_available()
            else:
                seen = " | ".join(e for e in echo if e.strip()) or "(no echo)"
                errors.append((ln, f"echo mismatch after 3 tries: {seen}"))
                print(f"\n  !! {ln}\n     echo mismatch, characters dropped: "
                      f"{seen}")
        bar.update(i)
    bar.done()
    return errors


def report_errors(errors):
    if errors:
        print(f"{len(errors)} line(s) rejected by the 8935:")
        for ln, t in errors:
            print(f"  {ln}\n     -> {t}")
        print("Fix those lines in the source and reload.")
    else:
        print("No errors reported during entry.")


def wait_bar(link, a, timeout=60):
    """Wait until the command bar answers again, rather than guessing.

    GET of a 700-line program takes longer than the 3 s this used to be given,
    and commands typed while it is still working are swallowed: the MSI and
    PURGE meant to free the transfer file went nowhere, STORE arrived six
    seconds later and landed, and the volume overflowed with SNDTMP still on
    it. Nothing reported an error, because nothing had failed - the commands
    were never seen. So ask the bar whether it is listening.

    The probe is arithmetic so the ANSWER is not in the echo: the bar echoes
    "PRINT 1+90134" and only prints 90135 once it has actually run it."""
    end = time.time() + timeout
    while time.time() < end:
        link.read_available()
        link.write_line("PRINT 1+90134", a.eol, a.char_delay)
        stop, buf = time.time() + 3, ""
        while time.time() < stop:
            buf += link.read_available()
            if "90135" in buf:
                return True
            time.sleep(0.2)
    print("  The command bar did not answer after GET; what follows may be "
          "typed into a\n  busy instrument and lost.")
    return False


def store(link, a):
    """PURGE then STORE, in that order and with the transfer file gone first.

    SNDTMP has done its job at GET and is still occupying the volume, which
    would otherwise have to hold it AND the stored program at this moment. On
    this unit SINADCTL is 167 records and the volume about 252, so the
    transfer file's ~94 do not fit alongside it."""
    print(f"Storing as {a.store} on {a.msus}")
    link.write_line(f'MSI "{a.msus}"', a.eol, a.char_delay)
    time.sleep(1.0)
    link.read_available()
    link.write_line('PURGE "SNDTMP"', a.eol, a.char_delay)
    time.sleep(1.5)
    r = link.read_available()
    # ERROR 56 is "file name is undefined" - the file is not there, which is
    # the state this PURGE exists to reach. Report every other code.
    if re.search(r"\bERROR\s+(?!56\b)\d+", r, re.I):
        print(f"  PURGE SNDTMP: {r.strip()}")
    elif "PURGE" not in r.upper():
        # no echo means the bar never saw it, which is how the transfer file
        # survived to overflow the volume at STORE
        print("  PURGE SNDTMP was not echoed; the command bar may be busy.")
    # PURGE before STORE: STORE refuses to overwrite with "ERROR 54 Duplicate
    # file name", which would silently leave --start loading a stale build.
    for c in (f'MSI "{a.msus}"', f'PURGE "{a.store}"', f'STORE "{a.store}"'):
        link.write_line(c, a.eol, a.char_delay)
        time.sleep(2.0)
        r = link.read_available()
        if re.search(r"\bERROR\s+\d+", r, re.I) and not c.startswith("PURGE"):
            print(f"  {c}: {r.strip()}")
            if "64" in r:
                # say what is actually on the volume rather than leaving the
                # operator to work out why it would not fit
                link.write_line(f'CAT "{a.msus}"', a.eol, a.char_delay)
                time.sleep(2.5)
                print("  volume now holds:")
                for ln in link.read_available().splitlines():
                    if ln.strip():
                        print(f"    {ln.strip()}")
                print("  The program in memory is running and usable; only "
                      "the stored copy is\n  missing, so --start has nothing "
                      "to run until a load succeeds.")


def run_program(link, a):
    link.read_available()
    link.write_line("RUN", a.eol, a.char_delay)
    print("RUN sent; waiting for SINADCTL...")
    end = time.time() + 30
    while time.time() < end:
        r = link.readline(0.5)
        if r and "READY" in r:
            print(f"  {r}")
            # --start runs whatever is stored, which after a power cycle or a
            # week away may predate the source on disk. The READY line carries
            # the version, so say so instead of starting it silently.
            check_version(r)
            return True
    print("  No READY reply. If the 8935 screen shows SINADCTL running, set\n"
          "  I/O CONFIGURE > Serial In = IBASIC by hand, then try:\n"
          "    python3 sinad.py ping")
    return False


def cmd_stream(a):
    """The two-stage load: type the small loader, then stream the program."""
    here = os.path.dirname(os.path.abspath(__file__))
    loader = os.path.join(here, "SERLOAD.BAS")
    link = open_link(a)
    require_state(link, a, BAR)
    clear_bar(link, a)
    main = program_lines(a.file, keep_comments=a.keep_comments)

    # Size the loader's RAM file to THIS program as the loader is typed,
    # rather than picking a number that has to be right forever. 80 records
    # was too small - ERROR 59, and the write fails a minute into the stream -
    # and 200 too big for the disc, ERROR 64 at CREATE. Each line costs its
    # characters plus a length word; records are 256 bytes; eight spare cover
    # the packing.
    need = sum(len(l) + 2 for l in main) + 2 * len(main)
    recs = -(-need // 256) + 8
    lines = [re.sub(r"(CREATE ASCII [^,]+,)\s*\d+", rf"\g<1>{recs}", l)
             for l in program_lines(loader)]

    print(f"Stage 1/2: typing the {len(lines)}-line loader "
          f"{os.path.basename(loader)} (RAM file {recs} records for "
          f"{need} bytes)")
    link.write_line("", a.eol, a.char_delay)
    time.sleep(0.3)
    link.read_available()
    link.write_line("SCRATCH", a.eol, a.char_delay)
    time.sleep(1.0)
    link.read_available()
    if not a.keep_stored:
        # The volume has to hold the stored program AND the incoming copy at
        # once, and that stopped fitting as SINADCTL grew. Dropping the stored
        # one first makes room. The cost is that a load which then fails
        # leaves nothing stored - and the source is on the laptop either way.
        print(f"  freeing the stored {a.store} to make room "
              f"(--keep-stored to skip)")
        for c in (f'MSI "{a.msus}"', f'PURGE "{a.store}"'):
            link.write_line(c, a.eol, a.char_delay)
            time.sleep(1.0)
            link.read_available()
    report_errors(type_lines(link, lines, a, "loader"))

    link.write_line("RUN", a.eol, a.char_delay)
    print("Stage 1/2: RUN; waiting for LOADER READY")
    ok, end = False, time.time() + 30
    while time.time() < end:
        r = link.readline(0.5)
        if r and "LOADER READY" in r:
            ok = True
            break
    if not ok:
        sys.exit(f"Loader did not answer. Check the 8935 screen.\n"
                 f"ERROR 64 at line 90 means the RAM disc could not spare "
                 f"{recs * 256} bytes for the\nfile: free some with PURGE on "
                 f"{a.msus}, or INITIALIZE it. ERROR 54 means a\nleftover "
                 f"SNDTMP is in the way.\nNothing was streamed.")
    link.set_xonxoff(True)

    # Preflight: send the first line on its own and have the loader read it
    # back. That exercises the whole path - serial out, the loader running,
    # the RAM file created, the write, serial back - before committing the
    # minute the rest takes. Without it the only check was the line count the
    # loader reports at the end, which is a minute too late to be useful.
    # The probe is the program's real first line, so nothing extra ends up in
    # the file.
    link.write_line(main[0], "\r\n")
    echo, end = None, time.time() + 12
    while time.time() < end:
        r = link.readline(0.3)
        if r and "LOADER FIRST" in r:
            echo = r.split("LOADER FIRST", 1)[1].strip()
            break
    if echo is None:
        link.set_xonxoff(False)
        sys.exit("The loader did not read back the first line.\n"
                 "It is running (it said LOADER READY) but nothing came back "
                 "from the write,\nso the RAM file is the suspect: try "
                 "INITIALIZE on " + a.msus + " at the front panel.\n"
                 "Nothing was streamed and the stored program is untouched.")
    if echo != main[0].strip():
        link.set_xonxoff(False)
        sys.exit(f"The loader read back a different first line.\n"
                 f"  sent: {main[0].strip()!r}\n  back: {echo!r}\n"
                 f"Characters are being lost or reordered on the link. "
                 f"Raising --char-delay\nor --stream-delay is the usual fix. "
                 f"Nothing was streamed.")
    print("Preflight: the loader read back line 1 intact.")

    print(f"Stage 2/2: streaming {len(main)} lines into 8935 RAM")
    bar = Progress(os.path.basename(a.file), len(main))
    bar.update(1)
    for i, ln in enumerate(main[1:], 2):
        link.write_line(ln, "\r\n")
        time.sleep(a.stream_delay)
        if i % 20 == 0 or i == len(main):
            bar.update(i)
    bar.done()
    print("Waiting for the loader to time out and close the file...")
    link.set_xonxoff(False)

    got, end = None, time.time() + 15
    while time.time() < end:
        r = link.readline(0.5)
        if r and r.startswith("LOADER DONE"):
            got = int(r.split()[-1])
            break
    # Whether the stream arrived intact decides whether we may touch the
    # stored copy. store() PURGEs before STORE, so going ahead on a short
    # stream destroys the last known-good program and replaces it with a
    # truncated one - which then loads without complaint and misbehaves later.
    if got is None:
        bad = ("The loader never reported a line count, so there is no way to "
               "tell\n  whether the stream arrived intact.")
    elif got != len(main):
        bad = (f"The loader saved {got} of the {len(main)} lines sent, so "
               f"{len(main) - got} were dropped.")
    else:
        bad = None
        print(f"  Loader saved all {got} lines.")
    if bad:
        print(f"\n  {bad}")
        print("  Not storing: that would PURGE the working copy and replace "
              "it")
        print("  with a truncated one. The stored program is untouched.")
        print(f"  --stream-delay was {a.stream_delay}; RAISE it and try "
              f"again:")
        print(f"    python3 load.py --stream-delay "
              f"{max(0.08, a.stream_delay * 2):g}")
        link.close()
        sys.exit(1)

    time.sleep(1.0)
    link.write_line('GET "SNDTMP"', a.eol, a.char_delay)
    time.sleep(1.0)
    r = link.read_available()
    if re.search(r"\bERROR\s+\d+", r, re.I):
        print(f'  GET "SNDTMP": {r.strip()}')
    wait_bar(link, a)
    if a.store:
        store(link, a)
    if a.run:
        run_program(link, a)
    link.close()


def cmd_direct(a):
    """Type every program line onto the command bar. ~2 s a line, so twenty
    minutes or more - for when the RAM disc will not cooperate, or when the
    loader itself is the suspect."""
    lines = program_lines(a.file, keep_comments=a.keep_comments)
    link = open_link(a)
    require_state(link, a, BAR)
    clear_bar(link, a)
    print(f"Direct load: typing {len(lines)} lines of "
          f"{os.path.basename(a.file)} onto the command bar "
          f"(about {len(lines) * 2 / 60:.0f} min on a real 8935).")
    link.write_line("", a.eol, a.char_delay)
    time.sleep(0.3)
    link.read_available()
    link.write_line("SCRATCH", a.eol, a.char_delay)
    time.sleep(1.0)
    link.read_available()
    report_errors(type_lines(link, lines, a, os.path.basename(a.file)))
    if a.store:
        store(link, a)
    if a.run:
        run_program(link, a)
    link.close()


def cmd_start(a):
    """Three typed lines, a few seconds: what you run every session."""
    link = open_link(a)
    require_state(link, a, BAR)
    clear_bar(link, a)
    link.write_line(f'MSI "{a.msus}"', a.eol, a.char_delay)
    time.sleep(1.5)
    # LOAD, not GET: STORE writes an IBPRG program file and GET is for ASCII
    # files. GET on a stored program answers "ERROR 58 Improper file type".
    link.write_line(f'LOAD "{a.name}"', a.eol, a.char_delay)
    time.sleep(3.0)
    r = link.read_available()
    if re.search(r"\bERROR\s+\d+", r, re.I):
        print(r.strip())
    run_program(link, a)
    link.close()


def build_parser():
    """Built separately from main() so a checker can introspect the options
    without importing a program that then drives an instrument."""
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", nargs="?", default=None,
                   help="program to load (default: SINADCTL.BAS beside this "
                        "script)")
    # dest is not "start": that reads as a level elsewhere, and sharing the
    # name across the two programs is how a configured sweep start once turned
    # into "skip loading".
    p.add_argument("--start", dest="start_stored", action="store_true",
                   help="do not load; LOAD the stored copy and RUN it")
    p.add_argument("--direct", action="store_true",
                   help="type every line onto the command bar (~20 min) "
                        "instead of streaming")
    p.add_argument("--name", default="SINADCTL",
                   help="--start: name of the stored program to LOAD")
    connection_args(p)

    g = p.add_argument_group("loading")
    g.add_argument("--no-run", dest="run", action="store_false", default=True,
                   help="load without running")
    g.add_argument("--store", metavar="NAME", default="SINADCTL",
                   help="STORE the program under this name so --start can "
                        "reload it. Empty string to skip")
    g.add_argument("--msus", default=":MEMORY,0,0",
                   help="mass storage for --store / --start")
    g.add_argument("--stream-delay", type=float, default=0.08,
                   help="seconds between streamed lines. 0.02 was tried on "
                        "hardware and fails silently; 0.08 works")
    g.add_argument("--line-timeout", type=float, default=4.0,
                   help="max seconds to wait for each typed line's echo")
    g.add_argument("--keep-stored", action="store_true",
                   help="do not purge the stored program before creating the "
                        "transfer file. The RAM disc cannot hold both at the "
                        "current program size - ERROR 64 at line 90")
    g.add_argument("--keep-comments", action="store_true",
                   help="also send comment-only lines")
    return p


def main():
    a = build_parser().parse_args()

    if a.start_stored:
        return cmd_start(a)
    if not a.file:
        a.file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "SINADCTL.BAS")
        if not os.path.exists(a.file):
            sys.exit(f"No program given and {a.file} is not there.")
    (cmd_direct if a.direct else cmd_stream)(a)


if __name__ == "__main__":
    main()
