#!/usr/bin/env python3
"""
sinad.py - talk to the SINADCTL program running on an HP 8935.

  python3 sinad.py ping                  is it alive, and which version
  python3 sinad.py term                  interactive: type a command, see the reply
  python3 sinad.py measure               a FAST sweep, points printed as they land
  python3 sinad.py measure --freq 145.55 --dev 1.5

Load the program first with load.py; this drives it. Nothing is written to
disk - the points go to stdout as they arrive, and that is the whole output.

`term` is what you reach for when something is wrong: it sends any SINADCTL
command (PING HELP STATUS SETUP FREQ DEV TONE PL PORT OFFSET AVG AVGC SETTLE
MAXLVL TARGET WIN FSTEP SSTEP TAIL SCREEN BRACKET UNCAP LEVEL RF READ FIND
FAST SWEEP AFLVL TRIG AFSC RFLIM AFTGT AFCMD AFPROBE SCPI SCPIQ QUIT) and
prints every line that comes back.

Ctrl-C at any point turns the generator off and waits for confirmation.

Add --sim to try it without hardware.  Requires pyserial.
Protocol, reply grammar and timing: PROTOCOL.md.
"""
import argparse, math, sys, threading, time

from link import (PROG, connection_args, converse, open_link, probe_state,
                  require_state, shutdown)

# What SINADCTL's phase codes mean, so the stream reads as phases rather than
# as a wall of points.
PHASE = {"C": "check", "B": "bisect", "S": "coarse", "F": "fine",
         "L": "linear", "R": "read"}
PHASE_NOTE = {
    "check": "above target at the top, below at the bottom?",
    "bisect": "bracketing the target",
    "coarse": "wider steps, for the shape of the curve",
    "fine": "small steps through the crossing",
    "linear": "a flat sweep",
    "read": "one averaged reading",
}


def uv(dbm):
    """dBm into 50 ohms as microvolts PD - how receiver sensitivity is quoted."""
    return math.sqrt(10 ** (dbm / 10) * .05) * 1e6


def configure(link, a):
    """Send every setting the measurement depends on, and read each answer.

    Nothing is assumed about what the last session left: a setting that is not
    sent is whatever is in the program's memory, and on this instrument
    sending one is not evidence it took - the reply is."""
    for cmd in (f"FREQ {a.freq}", f"DEV {a.dev}", f"TONE {a.tone}",
                f"TARGET {a.target}", f"MAXLVL {a.max_level}",
                f"AVG {a.avg}", f"AVGC {a.avg_coarse}",
                f"SETTLE {a.settle}"):
        r = converse(link, cmd)
        if r is None or r.startswith("ERR"):
            sys.exit(f"  {cmd} was not accepted; stopping rather than "
                     f"measuring in an unknown state.")
    if a.setup:
        print("  SETUP: generator and AF analyser chain")
        r = converse(link, "SETUP", timeout=60)
        if r is not None and r.startswith("ERR"):
            print("  SETUP reported instrument errors (the WARN lines above "
                  "carry them).")
            print("  A measurement taken now is in a state nobody checked.")


def cmd_ping(a):
    """Report where typed characters are going, and exit non-zero if that is
    not the running program. Reports rather than insists: unlike `measure`,
    this is the command you run precisely when you do not know the state."""
    link = open_link(a, assume_running=True)
    # probe_state prints the state and, for a running program, compares the
    # version in its reply against PROG_VERSION
    state = probe_state(link, a)
    if state != PROG:
        print("  SINADCTL is not answering. See README.md, 'Three things that")
        print("  will bite you', and PROTOCOL.md section 3 for this state.")
        print("  If the command bar is live:  python3 load.py --start")
    link.close()
    sys.exit(0 if state == PROG else 1)


def cmd_term(a):
    link = open_link(a, assume_running=True)
    state = {"stop": False, "quit": False, "last": time.time()}

    def reader():
        while not state["stop"]:
            r = link.readline(0.2)
            if r is not None:
                state["last"] = time.time()
                print(f"< {r}", flush=True)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    print("Type SINADCTL commands. Ctrl-D to exit; QUIT stops the program.")
    print("Try: PING / HELP / STATUS / SETUP / FAST -60 -130 / SCPIQ AFAN:INP?")
    interrupted = False
    try:
        for line in sys.stdin:
            if line.strip().upper().startswith("QUIT"):
                state["quit"] = True
            state["last"] = time.time()
            # paced: a character dropped inside a quoted SCPI string would be
            # accepted as a different setting, e.g. 'Open' arriving as 'Opn'
            link.write_line(line.rstrip("\n"), a.eol, a.char_delay)
        # End of input is not the end of the conversation: a FAST typed as the
        # last line is still streaming. Wait for the replies to go quiet
        # before tearing the reader down, or the tail of a sweep is thrown
        # away - which is exactly what happens when stdin is a pipe.
        end = time.time() + 60
        while time.time() < end and time.time() - state["last"] < 1.5:
            time.sleep(0.1)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if interrupted:
            print()
        # Stop the reader before shutting down: shutdown() needs the replies
        # to RF OFF and to the readback, and two consumers on one link means
        # neither sees a whole conversation.
        state["stop"] = True
        time.sleep(0.3)
        if state["quit"]:
            # Do_quit turns the generator off itself before it stops, so
            # asking again would only report that nothing is answering.
            print("  QUIT was sent; SINADCTL turns the generator off itself.")
        else:
            # Anything typed here could have started a sweep, and the
            # generator is the thing that radiates.
            shutdown(link, a)
        link.close()


def cmd_measure(a):
    """A FAST sweep, streamed. Each point is printed as it arrives."""
    link = open_link(a, assume_running=True)
    require_state(link, a, PROG)
    configure(link, a)

    print(f"\n  {a.freq} MHz   dev {a.dev} kHz   tone {a.tone:g} Hz   "
          f"avg {a.avg}/{a.avg_coarse}   target {a.target:g} dB SINAD")
    print(f"  sweeping {a.start} to {a.stop} dBm at the generator"
          + ("" if not a.offset else
             f"  (offset {a.offset:+g} dB -> at the fixture)"))

    result, phase, n = None, None, 0
    link.write_line(f"FAST {a.start} {a.stop}", a.eol)
    end = time.time() + a.max_time
    try:
        while time.time() < end:
            r = link.readline(0.1)
            if r is None:
                continue
            if r.startswith("PT,"):
                f = r.split(",")
                ph = PHASE.get(f[1], f[1])
                if ph != phase:
                    phase = ph
                    note = PHASE_NOTE.get(ph, "")
                    print(f"  -- {ph:<8s} {'-' * 12}  {note}")
                lvl, s = float(f[2]), float(f[3])
                # sinad -999 means no reading was valid; sd -1 means fewer
                # than two valid readings, so neither is a number to print
                sd = float(f[5]) if len(f) > 5 else -1.0
                shown = "   no reading" if s <= -998 else f"SINAD {s:6.2f} dB"
                print(f"  {lvl + a.offset:9.2f} dBm   {shown}"
                      + ("" if sd < 0 else f"   sd {sd:.2f}")
                      + f"   n={f[4]}", flush=True)
                n += 1
            elif r.startswith("BRACKET,"):
                lo, hi = (float(v) + a.offset for v in r.split(",")[1:3])
                print(f"     bracketed between {lo:.2f} and {hi:.2f} dBm",
                      flush=True)
            elif r.startswith("RESULT,"):
                result = [float(v) for v in r.split(",")[1:4]]
            elif r.startswith("WARN"):
                print(f"  {r}", flush=True)
            elif r.startswith("ERR"):
                print(f"  {r}", flush=True)
                if r.startswith("ERR HIGHLVL"):
                    # not terminal: the program then offers the generator's
                    # real ceiling at its own softkeys and waits up to 15 s,
                    # after which it either climbs again or ends. Keep reading.
                    got = r.split(",")[1:3]
                    reached = ""
                    try:
                        reached = f", reaching {float(got[1]):g} dB SINAD"
                    except (IndexError, ValueError):
                        pass
                    print(f"     The sweep climbed to the cap, "
                          f"{a.max_level:g} dBm{reached}, without making "
                          f"{a.target:g} dB.")
                    print("     Either the path loss is too high, the audio "
                          "is not connected, or the\n     receiver really is "
                          "that desensed. The program is waiting at its own\n"
                          "     softkeys for up to 15 s; this keeps reading.")
            elif r == "END":
                break
        else:
            print(f"\n  Gave up after {a.max_time:g} s without an END.")
    finally:
        # Ctrl-C lands here too. The generator is the thing that radiates, so
        # turning it off is not optional - and shutdown() waits for a sweep
        # in progress to finish, because SINADCTL does not read the serial
        # port during one: an RF OFF sent mid-sweep is acted on when the
        # sweep ends, not when it is sent.
        print()
        shutdown(link, a)

    print(f"\n  {n} points.")
    if result is None:
        print("  No RESULT: the fit needs at least 3 points between "
              f"{a.target - 5:g} and {a.target + 7:g} dB")
        print("  SINAD. The WARN line above says which case it was.")
    else:
        gen, at, _ = result
        print(f"  => {a.target:g} dB SINAD at {at:.2f} dBm "
              f"({uv(at):.3f} uV)"
              + ("" if not a.offset else f"   generator {gen:.2f} dBm"))
        print("     This is the level that produced the target, on this "
              "fixture. It is not")
        print("     an absolute sensitivity unless the path loss is in "
              "--offset.")
    link.close()


def build_parser():
    """Built separately from main() so a checker can introspect the options
    without importing a program that then drives an instrument."""
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ping", help="is the program alive, and which version")
    connection_args(sp)
    sp.set_defaults(func=cmd_ping)

    sp = sub.add_parser("term", help="interactive: send a command, see replies")
    connection_args(sp)
    sp.set_defaults(func=cmd_term)

    sp = sub.add_parser("measure", help="a FAST sweep, points as they arrive")
    connection_args(sp)
    g = sp.add_argument_group("measurement")
    # 145.55, not 146.52: that is the national FM simplex calling frequency,
    # and a repeating test tone radiated there lands on everyone monitoring
    # it. 145.50-145.80 is the miscellaneous and experimental segment, which
    # is what this is. Band plans are regional.
    g.add_argument("--freq", type=float, default=145.55, help="MHz")
    g.add_argument("--dev", type=float, default=3.0,
                   help="FM deviation of the test tone, kHz. 60%% of the "
                        "radio's maximum: 3 for a wide (5 kHz) radio, 1.5 for "
                        "narrowband")
    g.add_argument("--tone", type=float, default=1000.0,
                   help="modulating tone, Hz")
    g.add_argument("--start", type=float, default=-60.0,
                   help="top of the sweep, dBm")
    g.add_argument("--stop", type=float, default=-130.0,
                   help="bottom of the sweep, dBm")
    g.add_argument("--target", type=float, default=12.0,
                   help="SINAD target, dB")
    g.add_argument("--avg", type=int, default=8,
                   help="readings averaged per fine point")
    g.add_argument("--avg-coarse", type=int, default=3,
                   help="readings averaged per coarse point")
    g.add_argument("--settle", type=float, default=0.3,
                   help="seconds to wait after each level change")
    g.add_argument("--offset", type=float, default=0.0,
                   help="cable/pad loss, dB (negative), added to the levels "
                        "shown")
    # 0 dBm is 1 mW, which is enough to destroy a receiver front end built
    # for microvolts. The cap is the only thing between a sweep and the
    # generator's full output.
    g.add_argument("--max-level", type=float, default=-30.0,
                   help="the generator is never set above this, dBm")
    g.add_argument("--no-setup", dest="setup", action="store_false",
                   default=True,
                   help="do not send SETUP first (then the tone, deviation, "
                        "output port and the whole audio chain are whatever "
                        "the last user left)")
    g.add_argument("--max-time", type=float, default=900.0,
                   help="seconds to wait for the sweep to finish")
    sp.set_defaults(func=cmd_measure)
    return p


def main():
    a = build_parser().parse_args()
    try:
        a.func(a)
    except KeyboardInterrupt:
        # Each command's own `finally` has already turned the generator off
        # and said whether that was confirmed; this only keeps a traceback off
        # the screen, since a traceback here reads as a crash during cleanup.
        print("\nInterrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
