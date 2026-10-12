# hp8935-control — 12 dB SINAD measurement over RS-232

Measure a receiver's 12 dB SINAD sensitivity with an HP/Agilent 8935 (E6380A)
radio test set, driven from a laptop over its serial port. No GPIB adapter
needed.

Two programs:

1. **`load.py`** — puts `SINADCTL.BAS`, an IBASIC program, onto the 8935 and
   runs it. The program drives the instrument from the inside.
2. **`sinad.py`** — talks to it over the serial line: `ping`, `term`,
   `measure`.

`measure` runs a bisection-plus-fine-sweep search for the RF level that
produces 12 dB SINAD at the receiver's audio output, prints each point as it is
measured, and reports the fitted crossing. Nothing is written to disk.

Useful if you have one of these test sets and no GPIB interface, or if you want
a short, documented implementation of the serial protocol to build your own
controller on — [`PROTOCOL.md`](PROTOCOL.md) specifies the wire protocol
completely enough to do that without reading any of the Python.

```
python3 load.py --sim
python3 sinad.py measure --sim
```

Both work with no instrument attached and are the fastest way to see what this
does. `pip install pyserial` is the only dependency; the simulator needs
nothing at all.

| File | What it is | Lines |
|---|---|---|
| `link.py` | the serial link, the state probe, and a simulated 8935 | 806 |
| `load.py` | the loader | 450 |
| `sinad.py` | the live driver: `ping` / `term` / `measure` | 306 |
| `check_minimal.py` | version, documentation and simulator checks | 196 |
| `SINADCTL.BAS` | the IBASIC program that runs **on the 8935** | 870 |
| `SERLOAD.BAS` | the small receiver program the loader types in first, so the big one can be streamed | 36 |
| `PROTOCOL.md` | the wire protocol: commands, reply grammar, timing, loader sequence | — |

1562 lines of Python, 343 of which are the simulator and its commentary.

---

## The five-minute path

### 1. The 8935, at the front panel

**I/O CONFIGURE:** Serial In = **Inst**, IBASIC Echo = **On**, Baud **9600**,
Parity **None**, Data **8**, Stop **1**, Rcv Pace / Xmt Pace = **None**.

**Screen:** Software Menu → **TESTS (IBASIC CONTROLLER)**, and put the cursor
on the **command bar** — the highlighted strip at top left. If the 8935 beeps
and shows "Invalid keystroke" when you try to load, that cursor is what is
missing.

**Cabling:** a USB-serial adapter to the rear 9-pin connector, which carries
serial port 9. The generator's output is **DUPLEX OUT**; the radio's earphone
jack goes to **AUDIO IN**.

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

`measure` prints each point as it arrives — endpoints, bisection, coarse scan,
fine sweep — then the bracket and the fitted result:

```
  -- fine     ------------  small steps through the crossing
    -119.02 dBm   SINAD  12.44 dB   sd 0.57   n=8
    ...
  => 12 dB SINAD at -119.21 dBm (0.245 uV)
```

That level is what produced 12 dB SINAD **on your fixture**. It is an absolute
receiver sensitivity only if the path loss between the generator and the radio
is accounted for, which is what `--offset` is for.

If you want the points in a file, redirect stdout.

### 5. When something is wrong

```
python3 sinad.py term
```

Type any SINADCTL command and watch every line that comes back, including the
ones `measure` filters out. This is the tool to reach for first: the
instrument has several states that nothing on the bus can read, and a raw
`SCPIQ` through `term` will tell you what the instrument actually thinks far
faster than reasoning about parsed output will.

---

## Options

Small on purpose: there is no configuration file, so everything is a flag with
a default. `--help` on either program has the rest.

**`load.py`**

| Option | Default | |
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

| Option | Default | |
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
`sinad.py measure` it is the top of the sweep in dBm. They are kept from
sharing an internal name for that reason.

### Two options worth reading twice

**`--max-level`.** The cap is the only thing between a sweep and the
generator's full output. **0 dBm is 1 mW**, and the ceiling measured on
DUPLEX OUT of the one unit this was developed against is **+17.96 dBm** —
63 mW, which is a low-power transmitter rather than a signal-generator level,
and will destroy a receiver front end built for microvolts. The default of
−30 dBm is deliberately low. Raise it only when there are tens of dB of path
loss in the way, and never with a radio cabled straight to the port.

**`--dev`.** 3 kHz suits a wide, 25 kHz-channel radio: the convention is 60%
of the system's maximum deviation. Feeding 3 kHz to a narrowband radio
(12.5 kHz channel, 2.5 kHz maximum) over-deviates it, clips in its IF, and
makes it read worse than it is. Use `--dev 1.5` there.

---

## Scope

What the two programs do is load the IBASIC program and drive it. They do not
record, plot, or post-process anything: a run's points go to stdout and the
fitted crossing is printed once. There is no batch mode, no state kept between
runs, and no configuration file.

**`term` reaches every command the program has**, including the ones `measure`
does not use:

| | |
|---|---|
| `AFLVL`, `AFTGT`, `AFCMD`, `AFSC` | the AF level at AUDIO IN, for matching one radio's audio output to another's before comparing them |
| `AFPROBE` | reads the AF-level query and its units — worth running once on an unfamiliar instrument |
| `RFLIM` | asks the generator for its own output range on the port in use |
| `UNCAP` | raises the level cap to that measured ceiling |
| `SWEEP`, `READ`, `FIND` | a flat sweep, one averaged reading, and the bisection alone |
| `SCPI`, `SCPIQ` | send any instrument command or query, and read it back |
| `STATUS`, `HELP` | what the program currently has set, and its command list |

[`PROTOCOL.md`](PROTOCOL.md) documents all of them: arguments, replies, and
the timeouts each one needs.

---

## Checks

```
python3 check_minimal.py
```

| Check | Why |
|---|---|
| `link.PROG_VERSION` matches the `Ver$` literal in `SINADCTL.BAS`, and no second version literal exists anywhere in the program | The version in the `READY` line is the only way to tell from the laptop that a load actually took. Each side names it in exactly one place, so a stale build cannot look current. Earlier releases carried two copies of the number and they drifted apart — see [`PROTOCOL.md`](PROTOCOL.md) §12 |
| every option named in the documentation exists, and every example command parses | these documents have no other way of being told they have gone stale. The check is literal, so even naming a plausible-looking option in prose fails it |
| `load.py --sim` and `sinad.py measure --sim` run to completion | the only end-to-end tests there are, since the real ones need an instrument |
| *optional:* `SINADCTL.BAS` and `SERLOAD.BAS` byte-compared against reference copies one directory up | an integrity check for when those copies are present. With none there it says so and skips |

### About the simulator

`link.py` carries a simulated 8935 so that the protocol, the loader and the
measurement flow can be exercised with nothing attached. Two things to know
about it:

- **It models the commands these two programs send, plus the ones `term`
  obviously needs.** Any other real command answers
  `ERR SIM UNMODELLED <COMMAND>`, which is deliberately not something the
  instrument would ever say: a simulator limitation can never be mistaken for
  the instrument rejecting something. An actually unknown command still
  answers `ERR UNKNOWN`, as the instrument does.
- **Its measurement model is invented** — 12 dB SINAD near −119 dBm with
  Gaussian reading noise. It exercises the protocol. It is not a model of any
  radio, and no number it produces means anything.

---

## Three things that will bite you

[`PROTOCOL.md`](PROTOCOL.md) has the rest.

**1. Serial In survives a power cycle.** `SINADCTL` switches Serial In to
`IBASIC` when it starts and only restores `Inst` on `QUIT`. That setting is
part of I/O CONFIGURE and survives the power cycle, so if you power the 8935
off while the program is running it comes back with Serial In = `IBASIC` and
nothing running: characters arrive and go nowhere, and a perfectly good cable
looks dead. The fix is front-panel only — I/O CONFIGURE, Serial In = `Inst` —
and `QUIT` before powering off avoids it entirely.

**2. Nothing on the bus can restore the command bar.** The `DISPlay`
subsystem has no IBASIC-screen entry. Measured: `DISP?` *answers* `TIB` for
that screen, but `DISP TIB` is accepted, reports no error, and does not change
the screen. So after a session that ran `SETUP`, getting back to a state where
you can load is a front-panel action. Both programs probe for the state they
need and print the fix rather than typing into the wrong place.

**3. Sending a setting is not evidence it took.** This instrument accepts some
commands silently and ignores them, with no error and nothing in the error
queue, so `OK SCPI 0` means "nothing was rejected" and not "it worked".
Anything that changes the answer has to be read back. That is why `measure`
reads the reply to every setting it sends and stops rather than measuring in a
state nobody checked.

---

## Safety

**Ctrl-C turns the generator off.** Both `measure` and `term` shut it down on
the way out and then *read back* `RFG:AMPL:STAT?` to confirm, rather than
assuming. One honest limitation: `SINADCTL` does not read the serial port
while a sweep is running — its `ENTER` only happens in the main command loop —
so an `RF OFF` sent mid-sweep is acted on when the sweep **ends**, not when it
is sent. There is no abort. The shutdown waits for the sweep to finish and
says whether the generator actually stopped; if it cannot confirm, it tells
you to use the front panel's Stop.

**It radiates.** A sweep puts a repeating 1 kHz-modulated carrier on the air
through whatever is connected to the output. The default 145.55 MHz is in the
145.50–145.80 MHz miscellaneous and experimental segment, deliberately **not**
146.52, the national FM simplex calling frequency, where a repeating test tone
lands on everyone monitoring it. Avoid repeater inputs, 144.39 APRS and the
satellite subbands too. Band plans are regional: check your coordinator, and
listen before transmitting.

**Identify.** 47 CFR 97.119(a) wants your callsign at least every 10 minutes
during a communication and at the end of it, and Part 97 has no low-power or
test-signal exemption. Neither program here prompts for it, so it is entirely
on you. A single `measure` is well under 10 minutes; a string of them is not.
This is a plain reading of the rule, not legal advice.

## License

MIT — see [LICENSE](LICENSE). The HP/Agilent manual this cites is not
included and is not covered by it.
