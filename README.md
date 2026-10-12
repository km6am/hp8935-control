# minimal — load the program, talk to it, measure

Two capabilities and nothing else:

1. **`load.py`** — get `SINADCTL.BAS` onto an HP/Agilent 8935 (E6380A) and
   running.
2. **`sinad.py`** — talk to the running program: `ping`, `term`, `measure`.

Everything else the full tool does — sessions, CSV and plot output, PDFs,
uncertainty fitting, the desense analysis, the volume step, identification
timers, the config file, run replay — is **deliberately absent**. If you want
any of it, use the parent directory. The point of this folder is that you can
read all of it in a sitting, and that another implementer can see the protocol
working in the smallest honest amount of code.

```
python3 load.py --sim
python3 sinad.py measure --sim
```

Those two work with no instrument attached and are the fastest way to see what
this does. `pip install pyserial` is the only dependency; the simulator needs
nothing at all.

| File | What it is | Lines |
|---|---|---|
| `link.py` | the serial link, the simulator, the state probe | 804 |
| `load.py` | the loader | 450 |
| `sinad.py` | the live driver: `ping` / `term` / `measure` | 299 |
| `check_minimal.py` | drift, version, docs and simulator checks | 175 |
| `SINADCTL.BAS` | the IBASIC program that runs **on the 8935**. A byte-identical copy of the parent's | 870 |
| `SERLOAD.BAS` | the receiver the loader types onto the command bar first (31 lines once its comments are dropped). Also byte-identical | 36 |
| `PROTOCOL.md` | the wire protocol: commands, reply grammar, timing, loader sequence | 1136 |

About **1550 lines of Python** (1728 with the checker), of which 342 are the
simulator and its commentary. The parent is **5064 lines** across seven
programs, and the three this folder replaces — `hp8935.py`, `run.py`,
`load.py` — are 3487 of them.

---

## The five-minute path

### 1. The 8935, at the front panel

**I/O CONFIGURE:** Serial In = **Inst**, IBASIC Echo = **On**, Baud **9600**,
Parity **None**, Data **8**, Stop **1**, Rcv Pace / Xmt Pace = **None**.

**Screen:** Software Menu → **TESTS (IBASIC CONTROLLER)**, and put the cursor
on the **command bar** — the highlighted strip at top left. If the 8935 beeps
and shows "Invalid keystroke" when you try to load, that cursor is what is
missing.

**Cabling:** a USB-serial adapter to the rear 9-pin connector. The generator's
output is **DUPLEX OUT**; the radio's earphone jack goes to **AUDIO IN**.

### 2. Load the program

```
python3 load.py
```

About a minute and a half. It types a 31-line receiver program onto the
command bar, runs it, streams `SINADCTL.BAS` in at full rate, stores it in the
8935's battery-backed RAM disc and runs it. You should see:

```
  OK SINADCTL 2.3 READY
```

### 3. Every session after that

```
python3 load.py --start
```

A few seconds instead of a minute and a half: the stored copy survives a power
cycle, so this is the routine startup. A full load is only needed when
`SINADCTL.BAS` has changed — and the version in the `READY` line will tell you
when it has.

### 4. Measure

```
python3 sinad.py ping
python3 sinad.py measure --freq 145.55 --dev 3
```

`measure` runs a FAST sweep and prints each point as it arrives — endpoints,
bisection, coarse scan, fine sweep — then the bracket and the fitted result:

```
  -- fine     ------------  small steps through the crossing
    -119.02 dBm   SINAD  12.44 dB   sd 0.57   n=8
    ...
  => 12 dB SINAD at -119.21 dBm (0.245 uV)
```

Nothing is written to disk. If you want the points, redirect stdout.

### 5. When something is wrong

```
python3 sinad.py term
```

Type any SINADCTL command and watch the replies, including the ones
`measure` would have hidden. It is the tool that settles arguments: a raw
`SCPIQ` through `term` is what diagnosed the output-queue problem described in
`PROTOCOL.md` §10, after four attempts at reasoning from parsed output had
each made it worse.

---

## Flags

Small on purpose, since there is no config file. `--help` on either program has
the rest.

**`load.py`**

| Flag | Default | |
|---|---|---|
| `--start` | off | do not load; `LOAD` the stored copy and `RUN` it |
| `--direct` | off | type every program line onto the command bar (~20 min) instead of streaming |
| `--store` | `SINADCTL` | name to store under; empty string to skip storing |
| `--msus` | `:MEMORY,0,0` | mass storage for `--store` / `--start` |
| `--stream-delay` | `0.08` | seconds between streamed lines |
| `--char-delay` | `0.01` | seconds between characters typed onto the command bar |
| `--keep-stored` | off | do not purge the stored program before creating the transfer file |
| `--no-run` | — | load without running |
| `--port` / `--baud` / `--sim` | | the link |

**`sinad.py measure`**

| Flag | Default | |
|---|---|---|
| `--freq` | `145.55` | MHz |
| `--dev` | `3.0` | test-tone deviation, kHz. 60% of the radio's maximum: 3 for a wide (5 kHz) radio, **1.5 for narrowband** |
| `--tone` | `1000` | Hz |
| `--start` / `--stop` | `-60` / `-130` | sweep range, dBm |
| `--avg` / `--avg-coarse` | `8` / `3` | readings averaged per fine / coarse point |
| `--target` | `12` | SINAD target, dB |
| `--settle` | `0.3` | seconds after each level change |
| `--offset` | `0` | cable/pad loss in dB (negative), added to the levels shown |
| `--max-level` | `-30` | the generator is never set above this |
| `--no-setup` | — | skip `SETUP`, leaving the generator and audio chain as the last user left them |

**`--start` means two different things**, which is worth knowing before you
mistype it: on `load.py` it means "do not load, run the stored copy"; on
`sinad.py measure` it is the top of the sweep in dBm. The parent has the same
pair, and the two were deliberately kept from sharing an internal name after a
configured sweep level once turned into "skip loading".

### Two flags worth reading twice

**`--max-level`.** The cap is the only thing between a sweep and the
generator's full output. **0 dBm is 1 mW**, and the measured ceiling on
DUPLEX OUT of the one unit this was developed on is **+17.96 dBm** — 63 mW,
which is a low-power transmitter, not a signal-generator level, and will
destroy a receiver front end built for microvolts. The default of −30 dBm is
deliberately low. Raise it only when there are tens of dB of path loss in the
way, and never with a radio cabled straight to the port.

**`--dev`.** 3 kHz suits a wide, 25 kHz-channel radio. Feeding 3 kHz to a
narrowband radio over-deviates it, clips in its IF, and makes it read worse
than it is.

---

## What is not here, and why

| Cut | Where it lives |
|---|---|
| CSV / PNG / PDF output, run metadata | the parent's `run.py` |
| the uncertainty figure on the 12 dB level | the parent — it needs a second weighted fit on the laptop |
| `session`: batches, resume, settings-drift check | the parent |
| the volume step (`AFLVL` polling, `af_status`) | the parent. `AFLVL` is still a real command; `term` can send it |
| desense analysis, curve overlays, run replay | the parent's `desense.py`, `overlay.py`, `replay.py` |
| the config file and its schema | nowhere. Flags only, here |
| `monitor`, `afprobe`, `rflimit`, `state` as subcommands | the parent. `RFLIM` and `AFPROBE` are real commands; `term` can send them |

The one thing to know about that last row: **`term` can reach every command
the program has**, because the program is the same program. What `minimal/`
drops is the laptop-side apparatus around those commands, not access to them.

---

## This is a fork, not a library

`link.py`, `load.py` and `sinad.py` are **copies of the parent's logic,
trimmed** — not imports from it. A subfolder that reaches back into
`../hp8935.py` cannot be lifted out and used, which is the whole point of this
folder existing.

So: **the parent is the one that gets new features and new fixes.** When
something is learned on the bench it lands there first. This fork is expected
to lag, and `check_minimal.py` says what must not be allowed to lag:

```
python3 check_minimal.py
```

| Check | Why |
|---|---|
| `SINADCTL.BAS` and `SERLOAD.BAS` are **byte-identical** to the parent's | They are copies, not forks. The program that runs on the 8935 must be the same one both loaders load, or a bug fixed in one place survives in the other and the version in the `READY` line stops identifying a build. The parent's `check_bas.py` enforces this from its side too, so the root check fails if this folder drifts |
| `link.PROG_VERSION` matches the `Ver$` in `SINADCTL.BAS` | the laptop names a version in exactly one place and the program in exactly one place |
| every option named in the docs exists, every example command parses | these docs have no other way of being told they have gone stale. The check is literal, so even naming a plausible-looking option in prose fails it |
| `load.py --sim` and `sinad.py measure --sim` run to completion | the only end-to-end tests there are; nobody may open the serial port to make others |

### What needs syncing by hand

The `.BAS` files are checked. **The Python is not**, and these are the pieces
that will need carrying across when the parent changes:

- **The protocol handling in `link.py`**: `scpi_query`'s echo check, the
  state probe, `shutdown`. If the reply grammar gains a line type, the parent
  learns it first.
- **`PROG_VERSION`**, whenever `SINADCTL.BAS` is reloaded from the parent. The
  checker catches a mismatch, so this is a prompt rather than a trap.
- **The loader's measured constants** — `--stream-delay` 0.08, `--char-delay`
  0.01, the `+ 8` spare records, the 5 s end-of-stream silence. Each was
  learned the hard way; `PROTOCOL.md` §8 and the parent's `OPERATING.md` §5
  record why.
- **The trimmed simulator** in `link.py`, which models the commands these two
  programs send plus the ones `term` obviously needs. Anything else answers
  `ERR SIM UNMODELLED <COMMAND>` — a deliberately obvious string, so a real
  command that this simulator simply does not model can never be mistaken for
  one the instrument rejected. The measurement model behind it (12 dB SINAD
  near −119 dBm, Gaussian reading noise) is **invented**: it exercises the
  protocol, and it is not a model of any radio.

---

## Three things that will bite you

These are the ones that cost whole afternoons on the bench. `PROTOCOL.md` has
the rest.

**1. Serial In survives a power cycle.** `SINADCTL` switches Serial In to
`IBASIC` when it starts and only restores `Inst` on `QUIT`. That setting is
part of I/O CONFIGURE and survives the power cycle, so if you power the 8935
off while the program is running it comes back with Serial In = `IBASIC` and
nothing running: characters arrive and go nowhere, and a perfectly good cable
looks dead. The fix is front-panel only — I/O CONFIGURE, Serial In = `Inst` —
and `QUIT` before powering off avoids it entirely.

**2. Nothing on the bus can restore the command bar.** The `DISPlay`
subsystem has no IBASIC-screen entry (tested: `DISP?` *answers* `TIB` for it,
but `DISP TIB` is accepted, reports no error, and does nothing). So after a
session that ran `SETUP`, getting back to loading is a front-panel step.
`sinad.py` and `load.py` both probe for the state they need and print the fix
rather than typing into the wrong place.

**3. Sending a setting is not evidence it took.** This instrument accepts some
commands silently and ignores them, with no error and nothing in the error
queue. `OK SCPI 0` means "nothing was rejected", not "it worked". Anything
that changes the answer has to be read back — which is why `measure` reads the
reply to every setting it sends, and stops rather than measuring in a state
nobody checked.

---

## Safety

**Ctrl-C turns the generator off.** Both `measure` and `term` shut it down on
the way out and then *read back* `RFG:AMPL:STAT?` to confirm, rather than
assuming. One honest limitation: `SINADCTL` does not read the serial port
while a sweep is running — `ENTER` only happens in its main command loop — so
an `RF OFF` sent mid-sweep is acted on when the sweep **ends**, not when it is
sent. There is no abort. The shutdown waits for the sweep to finish and says
whether the generator actually stopped; if it cannot confirm, it tells you to
use the front panel's Stop.

**It radiates.** A sweep puts a repeating 1 kHz-modulated carrier on the air
through whatever is connected. The default 145.55 MHz is in the 145.50–145.80
miscellaneous and experimental segment, deliberately **not** 146.52, the
national FM simplex calling frequency. Band plans are regional; listen first.
And identify: 47 CFR 97.119(a) wants your callsign at least every 10 minutes
and at the end, with no low-power or test-signal exemption. The parent's tool
prompts for that between runs; **this one does not**, so it is entirely on
you. A single `measure` is well under 10 minutes; a string of them is not.
