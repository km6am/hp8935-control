#!/usr/bin/env python3
"""The serial link to an HP 8935, its simulator, and the state probe.

Shared by load.py (which needs the IBASIC command bar) and sinad.py (which
needs the SINADCTL program running). Nothing else is shared, which is why
this is the only module both import.

Everything here is either the link itself or a way of finding out what state
the instrument is in, because nothing on the 8935 announces that and nothing
resets it.
"""
import argparse, math, re, statistics, sys, time

# The SINADCTL version this module expects, named here and nowhere else.
# SINADCTL announces its own version in the READY line and in its answer to
# PING, both from one Ver$ literal - see check_version() for why that matters.
PROG_VERSION = "2.3"

# ---------------------------------------------------------------- state ----
# Where typed characters go. Nothing on the 8935 announces this and nothing
# resets it, so every command probes rather than assuming.
BAR = "command bar"          # Serial In = Inst, bar selected: lines execute
KEYS = "keystrokes ignored"  # Serial In = Inst, no field selected: echo only
PROG = "SINADCTL running"    # Serial In = IBASIC, the program answers
QUIET = "no response"        # nothing comes back at all

STATE_NOTE = {
    BAR: "Serial In = Inst, IBASIC command bar selected. Typed lines execute.",
    KEYS: "Serial In = Inst but no field is selected, so characters are "
          "rejected keystrokes (the 8935 shows \"Invalid keystroke\").",
    PROG: "Serial In = IBASIC and SINADCTL is answering.",
    QUIET: "nothing comes back. The 8935's own screen says which cause it is.",
}

BAR_FIX = ["Software Menu -> IBASIC Controller, then put the cursor on the",
           "command bar: the highlighted strip at top left."]

# KEYS and QUIET are not reliably distinguishable from here: with Serial In =
# Inst and no field selected the 8935 rejects the characters at the front
# panel and need not echo anything, which looks exactly like silence. So ask
# for the discriminator instead of guessing between four causes.
QUIET_FIX = [
    "Look at the 8935 while this runs. It says which of these it is:",
    "",
    "  It beeps / shows \"Invalid keystroke\"  ->  the link is fine and",
    "    Serial In = Inst. Only the command bar is missing:",
    "    Software Menu -> IBASIC Controller, cursor onto the command bar.",
    "    Most likely after a QUIT: nothing on the bus can restore that screen.",
    "",
    "  Nothing happens at all  ->  the characters are not reaching the front",
    "    panel. Most likely Serial In is still IBASIC with no program running,",
    "    which is the normal state after a POWER CYCLE - SINADCTL sets it and",
    "    only QUIT puts it back, and the setting survives the power cycle.",
    "    Fix at I/O CONFIGURE: Serial In = Inst.",
    "    Otherwise: a program hung inside a read (front panel Stop, not",
    "    Pause), or the link - port-9 connector, 9600, None, 8, 1, Pace None.",
]


# ----------------------------------------------------------- real link ----
class SerialLink:
    def __init__(self, port, baud=9600, xonxoff=False):
        import serial
        # exclusive=True so a second process is refused instead of both
        # scrambling the stream. Two programs on this port interleave their
        # bytes, which desynchronises SINADCTL's line-based protocol; that is
        # how a port collision once turned into a string overflow that killed
        # the running program.
        try:
            self.ser = serial.Serial(port, baud, bytesize=8, parity="N",
                                     stopbits=1, timeout=0.1, xonxoff=xonxoff,
                                     rtscts=False, exclusive=True)
        except TypeError:          # very old pyserial without exclusive=
            self.ser = serial.Serial(port, baud, bytesize=8, parity="N",
                                     stopbits=1, timeout=0.1, xonxoff=xonxoff,
                                     rtscts=False)
        self.buf = b""

    def set_xonxoff(self, on):
        self.ser.xonxoff = on

    def write_line(self, s, eol="\r\n", char_delay=0.0):
        """char_delay paces the bytes. The 8935's command bar has no flow
        control (Rcv Pace = None) and drops characters when a line arrives at
        full 9600 rate - observed on hardware as an 8-character echo of a
        9-character line, with the Enter dropped too, so nothing executed and
        nothing reported an error. Pacing is required, not belt-and-braces.
        The running program's ENTER is a real read and needs no pacing."""
        data = (s + eol).encode("ascii", "replace")
        if char_delay > 0:
            for b in data:
                self.ser.write(bytes([b]))
                self.ser.flush()
                time.sleep(char_delay)
        else:
            self.ser.write(data)
            self.ser.flush()

    def read_available(self):
        """Take whatever is already buffered. Never waits for more."""
        n = self.ser.in_waiting
        return self.ser.read(n).decode("ascii", "replace") if n else ""

    def readline(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            i = self.buf.find(b"\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 1:]
                # The 8935 pads with NUL, and NUL is not whitespace to
                # str.strip(), so leaving them in makes every echo compare
                # unequal.
                return line.decode("ascii", "replace").strip("\r\x00")
            self.buf += self.ser.read(self.ser.in_waiting or 1)
        return None

    def close(self):
        if self.ser is not None and self.ser.is_open:
            self.ser.close()


# ------------------------------------------------------------ simulator ----
# Every command SINADCTL 2.3 accepts. The simulator models the ones the
# minimal programs send, plus the ones `term` obviously needs; for the rest it
# answers ERR SIM UNMODELLED, which says plainly that the limit is here and
# not on the instrument. Never silently pretend.
REAL_COMMANDS = {
    "PING", "HELP", "SETUP", "FREQ", "DEV", "TONE", "PL", "PORT", "OFFSET",
    "AVG", "AVGC", "SETTLE", "MAXLVL", "TARGET", "WIN", "FSTEP", "SSTEP",
    "TAIL", "SCREEN", "BRACKET", "UNCAP", "LEVEL", "RF", "READ", "FIND",
    "FAST", "SWEEP", "STATUS", "AFLVL", "TRIG", "AFSC", "RFLIM", "SCPI",
    "SCPIQ", "AFTGT", "AFCMD", "AFPROBE", "QUIT",
}


class SimLink:
    """Simulated 8935: echoes command-bar lines, collects program text, and on
    RUN emulates SERLOAD or SINADCTL.

    The measurement model is INVENTED - 12 dB SINAD near -119 dBm with
    Gaussian reading noise. It exists so that the protocol, the loader and the
    measurement flow can be exercised with no instrument attached, which is
    also the only way any of this can be tested automatically. It is not a
    model of any radio and no number it produces means anything.
    """

    def __init__(self, line_time=0.01):
        import random
        self.rng = random.Random()
        self.out = []
        self.prog = {}
        self.mode = "inst"
        self.line_time = line_time
        self.last_rx = time.time()
        self.loader_lines = []
        self.files = {}
        self.st = dict(freq=146.52, lvl=-60.0, rf=False, navg=8, navgc=3,
                       tgt=12.0, brk=2.0, fstep=0.5, wa=6.0, wb=4.0,
                       sstep=5.0, hstart=-60.0, lstop=-130.0, maxlvl=-30.0,
                       ofs=0.0, port="Dupl", tail=True)
        # Whatever a previous user left on the screens. SCPI writes here and
        # SCPIQ reads it back, so the readback path is exercised - including
        # the case where a setting was never applied.
        self.scpi = {"CONF:SPOR9:SIN": "IBASIC", "DISP": "RFG",
                     "RFG:OUTP": "Dupl", "RFG:AMPL:STAT": "0",
                     "RFG:FREQ": "+1.46520000E+008", "CONF:RFD": "Freq",
                     "RFAN:FREQ": "+1.46520000E+008",
                     "AFAN:INP": "FM Demod", "MEAS:AFR:SEL": "Distn",
                     "AFAN:FILT1": "20Hz HPF", "AFAN:FILT2": "15kHz LPF",
                     "AFAN:DEMP": "Off", "AFAN:DET": "RMS",
                     "AFAN:RANG": "Auto", "AFAN:AIN": "Float"}

    def set_xonxoff(self, on):
        pass

    # ---- device side
    def _emit(self, s):
        # real hardware pads with NUL; model it so the stripping stays tested
        self.out.append(s + "\r\n\x00")

    def _sinad(self, lvl):
        if not self.st["rf"]:
            return 0.5
        snr = 12 + 2.2 * (lvl + 119.0)
        x = 10 ** (snr / 10)
        s = max(10 * math.log10(1 + x / (1 + x / 1e4)), 0.3)
        return s + self.rng.gauss(0, 0.4)

    def _meas(self, lvl, n, pc, pts):
        st = self.st
        lvl = min(lvl, st["maxlvl"])
        st["lvl"] = lvl
        n = max(1, int(n))
        reads = [self._sinad(lvl) for _ in range(n)]
        s = sum(reads) / n
        sd = statistics.stdev(reads) if n > 1 else -1.0
        pts.append((pc, lvl, s))
        self._emit(f"PT,{pc},{round(lvl, 2)},{round(s, 2)},{n},{round(sd, 3)}")
        return s

    def _fit(self, pts):
        st = self.st
        xs = [(l, s) for pc, l, s in pts
              if pc not in "BC" and st["tgt"] - 5 <= s <= st["tgt"] + 7]
        if len(xs) < 3:
            self._emit(f"WARN FIT NEEDS 3 POINTS NEAR TARGET, HAVE {len(xs)}")
            return
        n = len(xs)
        sx = sum(a for a, _ in xs); sy = sum(b for _, b in xs)
        sxx = sum(a * a for a, _ in xs); sxy = sum(a * b for a, b in xs)
        sl = (n * sxy - sx * sy) / (n * sxx - sx * sx)
        ic = (sy - sl * sx) / n
        r = (st["tgt"] - ic) / sl
        uv = math.sqrt(10 ** ((r + st["ofs"]) / 10) * .05) * 1e6
        self._emit(f"RESULT,{round(r, 2)},{round(r + st['ofs'], 2)},"
                   f"{round(uv, 3)}")

    def _find(self, hi, lo, pts):
        st = self.st
        s = self._meas(hi, st["navgc"], "C", pts)
        if s < st["tgt"] + 3:
            # same shape as SINADCTL's, so --sim exercises the real handler
            self._emit(f"ERR HIGHLVL,{round(hi, 2)},{round(s, 2)}")
            return None
        if self._meas(lo, st["navgc"], "C", pts) > st["tgt"]:
            self._emit("ERR SINAD AT LOW LEVEL STILL ABOVE TARGET")
            return None
        while hi - lo > st["brk"]:
            mid = (hi + lo) / 2
            if self._meas(mid, st["navgc"], "B", pts) >= st["tgt"]:
                hi = mid
            else:
                lo = mid
        self._emit(f"BRACKET,{round(lo, 2)},{round(hi, 2)}")
        return (hi + lo) / 2

    def _cmd(self, line):
        st = self.st
        w, _, a = line.strip().upper().partition(" ")
        # SINADCTL keeps an un-uppercased copy for the commands whose argument
        # is case-sensitive, so the simulator must too: 'C MESSAGE' is not
        # 'c message' to the instrument.
        raw_arg = line.strip().partition(" ")[2]
        nums = []
        for tok in a.split():
            try:
                nums.append(float(tok))
            except ValueError:
                pass
        if w == "PING":
            self._emit(f"OK SINADCTL {PROG_VERSION}")
        elif w == "HELP":
            self._emit("OK PING SETUP FREQ DEV TONE PL PORT OFFSET AVG AVGC")
            self._emit("OK SETTLE MAXLVL TARGET WIN FSTEP SSTEP TAIL SCREEN "
                       "UNCAP")
            self._emit("OK RF READ FIND FAST SWEEP STATUS QUIT")
            self._emit("OK AFLVL AFTGT AFCMD AFSC AFPROBE TRIG RFLIM SCPI "
                       "SCPIQ")
        elif w in ("FREQ", "OFFSET", "AVG", "AVGC", "TARGET", "MAXLVL",
                   "FSTEP", "SSTEP", "BRACKET", "DEV", "TONE", "SETTLE"):
            key = dict(OFFSET="ofs", AVG="navg", AVGC="navgc", TARGET="tgt",
                       BRACKET="brk").get(w, w.lower())
            st[key] = nums[0]
            if w == "FREQ":
                # FREQ sets CONF:RFD, the generator and the analyser together,
                # on the instrument. Modelled so the readback that caught a
                # front-panel change to 155 MHz surviving a run still works.
                self.scpi["CONF:RFD"] = "Freq"
                self.scpi["RFG:FREQ"] = f"{nums[0] * 1e6:+.8E}"
                self.scpi["RFAN:FREQ"] = f"{nums[0] * 1e6:+.8E}"
            self._emit(f"OK {w} {nums[0]}")
        elif w == "WIN":
            if len(nums) >= 2:
                st["wa"], st["wb"] = nums[0], nums[1]
            self._emit(f"OK WIN {a}")
        elif w == "PORT":
            st["port"] = "RF Out" if "RF" in a else "Dupl"
            self._emit(f"OK PORT {raw_arg}")
        elif w == "SETUP":
            self.scpi.update({"DISP": "AFAN", "AFAN:INP": "Audio In",
                              "MEAS:AFR:SEL": "SINAD", "CONF:RFD": "Freq",
                              "RFG:FREQ": f"{st['freq'] * 1e6:+.8E}",
                              "RFAN:FREQ": f"{st['freq'] * 1e6:+.8E}"})
            self._emit("OK SETUP")
        elif w == "STATUS":
            self._emit(f"OK FREQ {st['freq']} DEV 3 PL 0")
            self._emit(f"OK LEVEL {st['lvl']} OFFSET {st['ofs']} R12 -999")
            self._emit("OK AFLVL -1 AFTGT 1 AFQ MEAS:AFR:ACL?")
        elif w == "SCPI":
            root, _, val = raw_arg.partition(" ")
            if root:
                self.scpi[root.upper()] = val.strip().strip("'\"")
            self._emit("OK SCPI 0")
        elif w == "SCPIQ":
            root = raw_arg.strip().rstrip("?").upper()
            # echoed exactly as asked, which is what makes a slipped answer
            # detectable; see scpi_query()
            self._emit(f"SCPIQ,{raw_arg.strip()},{self.scpi.get(root, '')}")
        elif w == "LEVEL":
            st["lvl"] = min(nums[0], st["maxlvl"])
            self._emit(f"OK LEVEL {st['lvl']}")
        elif w == "RF":
            st["rf"] = a == "ON"
            self.scpi["RFG:AMPL:STAT"] = "1" if st["rf"] else "0"
            self._emit(f"OK RF {a}")
        elif w == "READ":
            self._meas(st["lvl"], st["navg"], "R", [])
            self._emit("END")
        elif w in ("FAST", "FIND"):
            hi = nums[0] if len(nums) > 0 else st["hstart"]
            lo = nums[1] if len(nums) > 1 else st["lstop"]
            st["hstart"], st["lstop"] = hi, lo   # FIND/FAST are sticky
            pts = []
            st["rf"] = True
            self.scpi["RFG:AMPL:STAT"] = "1"
            # climb to the cap when the start level does not clear the target,
            # as SINADCTL's Find does
            while hi < st["maxlvl"] - 1e-3:
                if self._sinad(hi) >= st["tgt"] + 3:
                    break
                hi = min(hi + 20, st["maxlvl"])
                self._emit(f"WARN RAISING START TO {hi:g} DBM")
            est = self._find(hi, lo, pts)
            if est is not None and w == "FAST":
                top = est + st["wa"]
                if st["sstep"] > 0:
                    l0 = hi
                    while l0 > top + 1:
                        self._meas(l0, st["navgc"], "S", pts)
                        l0 -= st["sstep"]
                l0 = top
                while l0 >= est - st["wb"] - .001:
                    self._meas(l0, st["navg"], "F", pts)
                    l0 -= st["fstep"]
                # the tail: coarse points below the fine window, down to the
                # level that was asked for, not to where bisection stopped
                if st["sstep"] > 0 and st["tail"]:
                    l0 = est - st["wb"] - st["sstep"]
                    while l0 >= lo - .001:
                        self._meas(l0, st["navgc"], "S", pts)
                        l0 -= st["sstep"]
                self._fit(pts)
            st["rf"] = False
            self.scpi["RFG:AMPL:STAT"] = "0"
            self._emit("END")
        elif w == "SWEEP":
            nums += [st["hstart"], st["lstop"], 1][len(nums):]
            pts, below, l0 = [], 0, nums[0]
            st["rf"] = True
            self.scpi["RFG:AMPL:STAT"] = "1"
            while l0 >= nums[1] - .001:
                s = self._meas(l0, st["navg"], "L", pts)
                below = below + 1 if s < 3 else 0
                l0 -= abs(nums[2])
                if below >= 3:
                    break
            self._fit(pts)
            st["rf"] = False
            self.scpi["RFG:AMPL:STAT"] = "0"
            self._emit("END")
        elif w == "QUIT":
            self._emit("OK BYE")
            self.mode = "inst"
        elif w in REAL_COMMANDS:
            # a real command this simulator does not model. Say so,
            # rather than answering ERR UNKNOWN and implying the instrument
            # would reject it.
            self._emit(f"ERR SIM UNMODELLED {w}")
        else:
            self._emit(f"ERR UNKNOWN {w}")

    def _finish_loader(self):
        self.files["SNDTMP"] = list(self.loader_lines)
        self._emit(f"LOADER DONE {len(self.loader_lines)}")
        self.mode = "inst"

    def write_line(self, s, eol="\r\n", char_delay=0.0):
        now = time.time()
        # SERLOAD ends the stream on a 5 s silence; there is no terminator
        if self.mode == "loader" and self.loader_lines and now - self.last_rx > 5:
            self._finish_loader()
        self.last_rx = now
        if self.mode == "inst":
            time.sleep(self.line_time)
            self._emit(s)  # the bar echoes what it received
            m2 = re.match(r"\s*PRINT\s+([-+*/0-9. ()]+)$", s.strip(), re.I)
            if m2:
                try:
                    self._emit(f" {eval(m2.group(1), {'__builtins__': {}}, {}):g}")
                except Exception:
                    self._emit("ERROR 2  Syntax error")
            m = re.match(r"\s*(\d+)\s(.*)$", s)
            u = s.strip().upper()
            if m:
                body = m.group(2)
                if body.count('"') % 2:
                    self._emit("ERROR 949  Syntax error at cursor")
                else:
                    self.prog[int(m.group(1))] = body
            elif u == "SCRATCH":
                self.prog = {}
            elif u.startswith("GET"):
                name = s.split('"')[1] if '"' in s else ""
                if name in self.files:
                    self.prog = {}
                    for ln in self.files[name]:
                        mm = re.match(r"\s*(\d+)\s(.*)$", ln)
                        if mm:
                            self.prog[int(mm.group(1))] = mm.group(2)
                else:
                    self._emit("ERROR 56  File name is undefined")
            elif u.startswith("STORE"):
                self.files[s.split('"')[1]] = [f"{k} {v}" for k, v
                                               in sorted(self.prog.items())]
            elif u.startswith("LOAD"):
                name = s.split('"')[1] if '"' in s else ""
                if name in self.files:
                    self.prog = {}
                    for ln in self.files[name]:
                        mm = re.match(r"\s*(\d+)\s(.*)$", ln)
                        if mm:
                            self.prog[int(mm.group(1))] = mm.group(2)
                else:
                    self._emit("ERROR 56  File name is undefined")
            elif u.startswith("PURGE") or u.startswith("MSI"):
                pass
            elif u == "RUN":
                text = " ".join(self.prog.values())
                if "SERLOAD" in text:
                    self.mode = "loader"
                    self.loader_lines = []
                    self._emit("LOADER READY")
                elif "SINADCTL" in text:
                    self.mode = "prog"
                    self._emit(f"OK SINADCTL {PROG_VERSION} READY")
        elif self.mode == "loader":
            self.loader_lines.append(s)
            if len(self.loader_lines) == 1:
                # SERLOAD reads the first line back so the loader can prove
                # the whole path before streaming the rest
                self._emit(f"LOADER FIRST {s}")
        elif self.mode == "prog":
            self._cmd(s)

    def readline(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            if (self.mode == "loader" and self.loader_lines
                    and time.time() - self.last_rx > 5):
                self._finish_loader()
            if self.out:
                return self.out.pop(0).strip("\r\n\x00")
            time.sleep(0.01)
        return None

    def read_available(self):
        s = "".join(self.out)
        self.out = []
        return s

    def close(self):
        pass


# ----------------------------------------------------------- port + open ---
# Adapter chips and naming worth ranking first in the picker.
_LIKELY = ("usbserial", "usbmodem", "ftdi", "ch340", "ch34", "cp210", "pl2303",
           "slab", "prolific", "silicon labs", "usb-serial", "usb serial")
_UNLIKELY = ("bluetooth", "debug-console", "wlan-debug", "debug console")


def list_serial_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        blob = f"{p.device} {p.description or ''} {p.manufacturer or ''}".lower()
        rank = (2 if any(k in blob for k in _UNLIKELY)
                else 0 if any(k in blob for k in _LIKELY) else 1)
        out.append((rank, p.device, (p.description or "").strip()))
    return sorted(out)


def connection_args(p):
    g = p.add_argument_group("connection")
    g.add_argument("--port", help="serial device, e.g. /dev/cu.usbserial-1410 "
                                  "or COM5. Omit it and the one likely "
                                  "candidate is used")
    g.add_argument("--baud", type=int, default=9600,
                   help="must match the 8935's I/O CONFIGURE screen")
    g.add_argument("--sim", action="store_true",
                   help="simulated 8935, no hardware, no serial port opened")
    # only for debugging an adapter that mangles one line ending
    g.add_argument("--eol", default="\r\n", help=argparse.SUPPRESS)
    g.add_argument("--char-delay", type=float, default=0.01,
                   help="seconds between characters typed onto the command "
                        "bar. The bar has no flow control and drops "
                        "characters at full line rate")
    return g


# One simulator per process, so load.py's stages and a later measure() see the
# same instrument. Hardware is one device too.
_SIM = None


def open_link(a, xonxoff=False, assume_running=False):
    global _SIM
    if a.sim:
        if _SIM is None:
            _SIM = SimLink()
            if assume_running:
                # the measurement commands assume the program is already there
                _SIM.mode = "prog"
        return _SIM
    port = a.port
    if not port:
        ports = list_serial_ports()
        likely = [d for r, d, _ in ports if r == 0]
        if len(likely) == 1:
            port = likely[0]
            print(f"Using {port} (the one likely serial adapter)")
        else:
            lines = "\n".join(f"    {d}  {desc}" for _, d, desc in ports)
            sys.exit("Pass --port: there is no single obvious serial adapter."
                     + (f"\n  Available:\n{lines}" if ports
                        else "\n  No serial ports found.")
                     + "\n  Or use --sim to work without hardware.")
    try:
        return SerialLink(port, a.baud, xonxoff)
    except Exception as e:
        if "resource busy" in str(e).lower() or "exclusive" in str(e).lower():
            sys.exit(f"{port} is already open in another process.\n"
                     "Only one program can drive the 8935 at a time: two sets "
                     "of bytes interleave,\nwhich desynchronises SINADCTL's "
                     "protocol and can hand it a malformed command.")
        sys.exit(f"Could not open {port} at {a.baud} baud: {e}\n"
                 "Use --sim to work without hardware.")


# ------------------------------------------------------------- probing ----
def _collect(link, seconds, stop=None):
    """Read lines for up to `seconds`, or until stop(buf) is satisfied.

    The budget is a worst case, not a dwell: without the stop test this waited
    the whole time even when the answer arrived in 100 ms, on every command."""
    buf, end = "", time.time() + seconds
    while time.time() < end:
        r = link.readline(0.1)
        if r is not None:
            buf += r + "\n"
            if stop is not None and stop(buf):
                break
    return buf


def clear_bar(link, a, n=120):
    """Leave the command bar empty.

    Stale text is not harmless: a leftover fragment turned PRINT 1+1 into
    PRINT 1PI on the screen. Preset does NOT clear the bar - confirmed on
    hardware - so backspaces are the only thing that does. The bare Enter
    afterwards submits and discards anything that survived them, at a cost of
    at most one harmless syntax error."""
    gap = max(getattr(a, "char_delay", 0.01), 0.004)
    link.write_line("\x08" * n, "", gap)
    time.sleep(0.2)
    link.write_line("", getattr(a, "eol", "\r\n"), gap)
    time.sleep(0.3)
    link.read_available()


def check_version(reply, announce=True):
    """Compare the version in a READY or PING reply with PROG_VERSION.

    The version is read out of whatever line the program sent, never written
    down a second time here: in SINADCTL 2.0-2.2 the PING case carried its own
    "1.9" while READY carried the real version, so a correctly loaded program
    asked to be reloaded on every run - a warning worse than none, because it
    trains the reader to ignore the real one. The program now holds one Ver$
    and sends it in both lines, and this is the only place on this side that
    names a version."""
    m = re.search(r"SINADCTL\s+([0-9]+(?:\.[0-9]+)*)", reply)
    if not m:
        return None
    got = m.group(1)
    if got != PROG_VERSION and announce:
        key = lambda s: tuple(int(p) for p in s.split("."))
        rel = "older than" if key(got) < key(PROG_VERSION) else "newer than"
        print(f"  NOTE the 8935 is running SINADCTL {got}, {rel} this copy "
              f"({PROG_VERSION}). Reload it: python3 load.py")
    return got


def probe_state(link, a, announce=True):
    """Work out where typed characters are going, by observation."""
    link.read_available()
    link.write_line("PING", getattr(a, "eol", "\r\n"),
                    getattr(a, "char_delay", 0.01))
    reply = _collect(link, 3, lambda b: "SINADCTL" in b and "OK" in b)
    if "SINADCTL" in reply and "OK" in reply:
        state = PROG
        check_version(reply, announce)
    else:
        clear_bar(link, a)
        link.write_line("PRINT 1+1", getattr(a, "eol", "\r\n"),
                        getattr(a, "char_delay", 0.01))
        # the bar echoes the line and then prints the result, so wait for a 2
        # on a line of its own rather than for the clock
        echo = _collect(link, 3,
                        lambda b: any(l.strip() == "2" for l in b.splitlines()))
        if "2" in echo.replace("PRINT 1+1", "", 1):
            state = BAR
        elif echo.strip():
            state = KEYS
        else:
            state = QUIET
    if announce:
        print(f"  8935 state: {state} - {STATE_NOTE[state]}")
    return state


def require_state(link, a, want):
    """Probe, and only continue if we are where we need to be.

    One automatic recovery is safe and covers the common case: if SINADCTL is
    running and we need the command bar, QUIT asks it to put Serial In back to
    Inst itself, which is the only clean way out of that mode."""
    state = probe_state(link, a)
    if state == want:
        return state
    if want == BAR and state == PROG:
        print("  SINADCTL is running; sending QUIT so it restores "
              "Serial In = Inst")
        link.write_line("QUIT", getattr(a, "eol", "\r\n"),
                        getattr(a, "char_delay", 0.01))
        # QUIT answers OK BYE and only THEN switches Serial In back
        _collect(link, 5, lambda b: "OK BYE" in b)
        time.sleep(1.0)
        state = probe_state(link, a, announce=False)
        if state == want:
            print(f"  8935 state: {state} - {STATE_NOTE[state]}")
            return state
        # QUIT did its half. The other half cannot be done from here at all:
        # the DISPlay subsystem has no IBASIC screen (tested), so nothing on
        # the bus can bring the command bar back, and SETUP left AF ANALYZER
        # up. "Wrong baud or powered off" would send you looking in the wrong
        # place for something that is working correctly.
        print("\n  QUIT worked - Serial In is back to Inst. What is missing is")
        print("  the IBASIC command bar, and no bus command can bring it back:")
        print("  the DISPlay subsystem has no IBASIC screen. Front panel only:")
        for line in BAR_FIX:
            print(f"    {line}")
        sys.exit("Stopping rather than typing into the wrong place.")
    print(f"\n  Need: {want} - {STATE_NOTE[want]}")
    for line in (BAR_FIX if state == KEYS else
                 QUIET_FIX if state == QUIET else []):
        print(f"    {line}")
    if want == PROG and state == BAR:
        print("    The command bar is live but SINADCTL is not running.")
        print("    Start it:  python3 load.py --start")
    sys.exit("Stopping rather than typing into the wrong place.")


# ------------------------------------------------------- talking to it ----
def converse(link, cmd, timeout=10):
    """Send cmd, return its OK/ERR line. WARN lines are printed and skipped."""
    link.write_line(cmd, "\r\n")
    end = time.time() + timeout
    while time.time() < end:
        r = link.readline(0.2)
        if r is None:
            continue
        if r.startswith("WARN"):
            print(f"  {r}")
            continue
        if r.startswith(("OK", "ERR")):
            if r.startswith("ERR"):
                print(f"  {cmd}: {r}")
            return r
    print(f"  {cmd}: no reply")
    return None


def scpi_query(link, query, timeout=20, tries=2):
    """Ask the instrument one SCPI query through the program. (value, problem).

    SINADCTL echoes the query back beside its answer, and checking that echo
    is the whole point: a reply that has slipped by one query is otherwise
    indistinguishable from the right answer, and a desynchronised output queue
    then reports a screenful of plausible, entirely wrong state.

    A mismatch means something narrower than it looks. The program echoes the
    argument of the command it just received, so the echo cannot disagree
    because of anything on the instrument bus - only because this reply
    belongs to an EARLIER query whose answer is still in OUR serial buffer,
    abandoned on a timeout. Hence the discard before sending."""
    v = problem = None
    for attempt in range(tries):
        v, problem = _scpi_query_once(link, query, timeout)
        if v is not None or not problem or "out of step" not in problem:
            return v, problem
        if attempt + 1 < tries:
            print(f"  {problem}; asking again")
    return v, problem


def _scpi_query_once(link, query, timeout):
    # Anything buffered now is the tail of a query we already gave up on.
    # Reading it as this query's answer is what made each abandoned query
    # poison its successor - and the lag then GREW: 1, 1, 2, 2, 3...
    link.read_available()
    link.write_line(f"SCPIQ {query}", "\r\n")
    end, problem = time.time() + timeout, None
    while time.time() < end:
        r = link.readline(0.2)
        if r is None:
            continue
        if r.startswith("SCPIE,"):
            echo, _, msg = r[len("SCPIE,"):].partition(",")
            problem = msg.strip() or echo.strip()
            continue
        if r.startswith("SCPIQ,"):
            echo, sep, ans = r[len("SCPIQ,"):].partition(",")
            if not sep:
                return None, ("the program cannot confirm which query it "
                              "answered; reload it with load.py")
            if echo.strip().upper() != query.strip().upper():
                return None, (f"the 8935 answered {echo.strip()!r}, not "
                              f"{query!r} - its output queue is out of step")
            ans = ans.strip().strip("'\"")
            return (ans if ans else None), (problem if not ans else None)
        if r.startswith(("ERR", "WARN")):
            print(f"  {r}")
    return None, problem or f"no answer to {query}"


def shutdown(link, a, drain=25.0):
    """Leave the 8935 not transmitting, and say whether that worked.

    The sweep loop in SINADCTL does not read the serial port - ENTER Sp only
    happens in the main command loop - so RF OFF sent during a sweep is
    buffered and acted on when the sweep ends, not when it is sent. There is
    no way round that from here, so this waits for the sweep to finish and
    says plainly whether the generator stopped, rather than pretending.

    Returns True when the generator is confirmed off."""
    try:
        link.write_line("RF OFF", getattr(a, "eol", "\r\n"))
        end = time.time() + drain
        while time.time() < end:
            r = link.readline(0.2)
            if r is None:
                continue
            if r.startswith("OK RF"):
                break
        v, _ = scpi_query(link, "RFG:AMPL:STAT?", timeout=8)
        off = v is not None and v.strip().lstrip("+") in ("0", "OFF")
        if off:
            print("  RF generator off.")
        else:
            print(f"  WARNING could not confirm the generator is off "
                  f"(RFG:AMPL:STAT? said {v!r}).")
            print("  Press the front panel's Stop, or check the RF GENERATOR "
                  "screen.")
        return off
    except Exception as e:
        print(f"  Could not shut the generator down cleanly: {e}")
        print("  Stop the program from the 8935's front panel.")
        return False


def fmt_dur(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}m{sec % 60:02d}s" if sec >= 60 else f"{sec}s"


class Progress:
    """One-line progress bar for the long load. Falls back to periodic plain
    lines when stdout is not a terminal, so a captured log stays readable."""

    def __init__(self, label, total, width=22):
        self.label, self.total, self.width = label, max(1, total), width
        self.t0, self.tty, self.last = time.time(), sys.stdout.isatty(), -1

    def update(self, i):
        frac = min(1.0, i / self.total)
        elapsed = time.time() - self.t0
        eta = (elapsed / i) * (self.total - i) if i else 0
        filled = int(round(frac * self.width))
        bar = "#" * filled + "." * (self.width - filled)
        line = (f"  {self.label}  [{bar}] {i:>4}/{self.total}  "
                f"{frac * 100:3.0f}%  {fmt_dur(eta)} left")
        if self.tty:
            print("\r" + line.ljust(78), end="", flush=True)
        elif i == self.total or i // 50 != self.last // 50:
            print(line, flush=True)
        self.last = i

    def done(self, note=""):
        took = fmt_dur(time.time() - self.t0)
        line = (f"  {self.label}  {self.total} lines in {took}"
                + (f"  {note}" if note else ""))
        print("\r" + line.ljust(78) if self.tty else line, flush=True)
