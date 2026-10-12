# Serial protocol reference — SINADCTL on an HP 8935

> **This is the copy that ships with `minimal/`.** The canonical version is
> `../PROTOCOL.md` in the parent directory; this one is the same document with
> the references to the full tool's features removed, so that a lifted-out
> `minimal/` is complete on its own. If the two ever disagree, the parent is
> right. The *protocol* itself is identical either way, because `minimal/`
> ships a byte-identical copy of `SINADCTL.BAS`.

**Audience: somebody writing their own controller.** Everything needed to drive
`SINADCTL` over RS-232 without reading any of the Python here. If you want to
*use* the two programs in this folder rather than replace them, read
[`README.md`](README.md); for the bench history behind a claim here, the
parent directory's `CLAUDE.md` is the lab notebook.

**Provenance of everything below.** The command set, the argument forms and the
reply grammar are read off `SINADCTL.BAS`'s own dispatch (`Parse`, `SELECT W$`)
and its emitting lines — not from prose, not from memory, and in two places
they disagree with the parent's `README.md`, which is noted where it happens.
Behaviour of
the *instrument* traces to the *Agilent 8935 Series E6380A GPIB Syntax
Reference*, E6380-90073 Rev E (`9018-70126.pdf`, cited by its own page
numbers), or to bench measurement on **one** unit, marked *measured*. Timing
figures marked *measured* come from logged run timestamps. §13 lists what could
not be established at all.

This describes **SINADCTL 2.3**. The program announces its version in two
places and they now come from one literal; §12 says why that is worth a
paragraph.

---

## Contents

1. [The physical link](#1-the-physical-link)
2. [Two layers, and why that is the thing to get right](#2-two-layers-and-why-that-is-the-thing-to-get-right)
3. [The state machine](#3-the-state-machine)
4. [Line framing and command grammar](#4-line-framing-and-command-grammar)
5. [The command set](#5-the-command-set)
6. [The reply grammar](#6-the-reply-grammar)
7. [A worked exchange](#7-a-worked-exchange)
8. [Loading the program over the same wire](#8-loading-the-program-over-the-same-wire)
9. [Timing and timeouts a client must allow](#9-timing-and-timeouts-a-client-must-allow)
10. [Error-queue discipline on bus 800](#10-error-queue-discipline-on-bus-800)
11. [SCPI rules that actually apply on this instrument](#11-scpi-rules-that-actually-apply-on-this-instrument)
12. [Quirks that will cost you an afternoon](#12-quirks-that-will-cost-you-an-afternoon)
13. [What could not be established from the repo](#13-what-could-not-be-established-from-the-repo)

---

## 1. The physical link

| | |
|---|---|
| Connector | the 8935's rear 9-pin serial connector, which carries serial ports 9, 10 and 11. The program uses **port 9** |
| Rate | **9600 baud** |
| Framing | **8 data bits, no parity, 1 stop bit** |
| Hardware flow control | **none** (no RTS/CTS) |
| Software flow control | **none**, except during stage 2 of a program load — see §8 |
| 8935 front-panel setup | I/O CONFIGURE: Serial In per §3, IBASIC Echo **On**, 9600, None, 8, 1, Rcv Pace **None**, Xmt Pace **None** |

*Measured* on this unit with two different USB-serial adapters, one an FT232R;
`cu.*` and `tty.*` device nodes behave identically. The DTE/DCE pinout was
never confirmed from a manual — the existing cable works, so a new cable is
uncharted territory and a null-modem adapter is the first thing to try
(*inference, untested*).

**Open the port exclusively.** Two processes on this port interleave their
bytes, which desynchronises the line-based protocol and hands the program
malformed commands. *Measured:* that turned into a string overflow that killed
the running program.

### Pacing: required in one direction, not the other

This is the single most important link-layer fact, and it is asymmetric.

- **Typing onto the command bar needs pacing.** In `Inst` mode the bytes you
  send are keystrokes, and the command bar **has no flow control and drops
  characters at full line rate**. *Measured:* a 9-character line arrived as 8
  characters, the Enter among them, so nothing executed at all and nothing
  reported an error. **Pace at 10 ms per character minimum**; 25 ms is
  comfortably reliable. Flush after each byte — buffering the line and letting
  the OS write it defeats the point.
- **Talking to the running program needs no pacing.** In `IBASIC` mode the
  bytes go to the program's `ENTER` statement, which is a real read with a real
  buffer. Write whole lines at full rate.
- **The program's replies need no pacing and no flow control** in either
  direction. Read them as a stream and split on newline.

### Reading replies

Replies are CR-LF terminated. **The 8935 pads with NUL**, and NUL is not
whitespace to most languages' `strip()` — leaving them in makes every echo
comparison fail. Strip `\r` and `\x00` from both ends of every line.

Send `\r\n` as the line terminator. The program defensively trims a trailing CR
from each command it receives, so a bare `\n` also works, but CR-LF is what is
tested.

---

## 2. Two layers, and why that is the thing to get right

Newcomers try to send SCPI down the serial port. It will never work, and the
reason is worth stating plainly:

> **Serial characters are keystrokes or IBASIC program input. They are never
> SCPI.** E6380-90073 is the *GPIB* syntax reference: SCPI reaches this
> instrument over **HP-IB only**. *Measured, and it is the architectural fact
> the whole project follows from.*

So the design is:

```
   your program                     the 8935
  ┌────────────┐   RS-232 9600    ┌──────────────────────────────────┐
  │  client    │ ───────────────► │ serial port 9                    │
  │            │ ◄─────────────── │   │                              │
  └────────────┘   text lines     │   ▼                              │
                                  │ SINADCTL.BAS  (IBASIC program)   │
                                  │   │  OUTPUT 800;"..."            │
                                  │   │  ENTER  800;V                │
                                  │   ▼                              │
                                  │ internal instrument bus 800      │
                                  │   = the generator, the analyser  │
                                  └──────────────────────────────────┘
```

`SINADCTL` runs **on** the instrument. Your text lines are its commands; it
translates them into SCPI on bus 800 and sends results back as text.

### How SCPI tunnels through

You are not limited to the measurement commands. Two generic commands forward
anything to bus 800, which is how the audio-analyser chain gets configured and
read back without reloading the program:

**`SCPI <command>`** — fire and forget, with an error count:

```
→  SCPI AFAN:FILT2 '3kHz LPF'
←  OK SCPI 0
```

Internally: `*CLS`, then `OUTPUT 800;<your command, case preserved>`, then the
error queue is read. The `0` is the number of instrument errors that followed.
If it is non-zero you also get a `SCPIE` line naming the instrument's own
words (§6).

**`SCPIQ <query>`** — query, with the query **echoed back beside the answer**:

```
→  SCPIQ AFAN:FILT2?
←  SCPIQ,AFAN:FILT2?,"3KHZ LPF"
```

**The echo is not decoration and you must check it.** Compare it
case-insensitively against the query you just sent. A mismatch means this reply
belongs to an *earlier* `SCPIQ` whose answer you abandoned on a timeout — the
whole readback is lagging by one, and without the echo a lagged reply is
indistinguishable from the right answer. *Measured:* before the echo existed, a
desynchronised queue reported a full screen of plausible and entirely wrong
instrument state. See §10 for what to do about it.

Note what the mismatch does and does not tell you: the program echoes the
argument of the command **it just received**, so the echo cannot disagree
because of anything happening on bus 800. It can only disagree if the reply is
sitting in *your own* serial buffer from a previous query. The lag is on your
side of the wire.

Three details that bite:

- **Case is preserved for `SCPI`, `SCPIQ`, `AFCMD` and `PORT` arguments only.**
  Everything else is upper-cased by the dispatcher. `'C MESSAGE'` is not
  `'c message'`, and the instrument cares.
- **Answers come back upper-cased and in double quotes** — `"SINAD"`,
  `"AUDIO IN"`, `3KHZ LPF` — while the instrument *accepts* the manual's mixed
  case going in. Strip quotes and compare case-insensitively.
- **The answer buffer is 80 characters.** A longer reply is truncated.

---

## 3. The state machine

Nothing on the 8935 announces where your typed characters are going, and
nothing resets on its own. There are four states. The names are the ones the
existing tooling prints, so they are worth keeping.

| State | Serial In | What your bytes do | Needed for |
|---|---|---|---|
| **BAR** | `Inst` | keystrokes into the **selected IBASIC command bar**: a typed line executes | loading a program |
| **KEYS** | `Inst` | keystrokes rejected at the front panel — no field is selected, the 8935 beeps and shows "Invalid keystroke" | nothing; it is a fault state |
| **PROG** | `IBASIC` | input to the running program's `ENTER 9` | everything in §5 |
| **QUIET** | either | nothing comes back | nothing; it is a fault state |

`SINADCTL` **sets Serial In to `IBASIC` itself at startup** and restores `Inst`
only on `QUIT`. That setting lives in I/O CONFIGURE and *survives a power
cycle* (*measured*), so the instrument can boot into `IBASIC` with nothing
running — characters then go nowhere and a perfectly good cable looks dead.

### Probing for the state

```
1. discard anything already buffered
2. send  PING
3. if a line matching  OK SINADCTL <version>  arrives within ~3 s   → PROG
4. otherwise:
     a. clear the command bar (see below)
     b. send  PRINT 1+1
     c. collect for ~3 s
        - a line that is just "2"          → BAR
        - any other non-empty output       → KEYS
        - nothing at all                   → QUIET
```

**Clearing the command bar first is not optional.** Stale text on the bar is
not inert: a leftover fragment turned `PRINT 1+1` into `PRINT 1PI` on the
screen. *Measured:* **Preset does not clear the bar** — only backspaces do.
Send ~120 backspace characters (`0x08`, paced like any other keystroke), then a
bare Enter, which submits and discards anything that survived; the cost is at
most one harmless syntax error.

### The honest limitation

**KEYS and QUIET are not reliably distinguishable from your side of the wire.**
With Serial In = `Inst` and no field selected, the 8935 rejects the characters
at the front panel and **need not echo anything**, which looks exactly like
silence. Do not build a decision tree that pretends otherwise. The
discriminator is on the instrument's screen, so a client should say so and ask:

- **it beeps / shows "Invalid keystroke"** → the link is fine and Serial In is
  `Inst`; only the command bar is unselected. Front panel: Software Menu →
  IBASIC Controller, cursor onto the highlighted strip at top left. This is the
  usual state after a `QUIT`, because **nothing on the bus can restore that
  screen** (§11).
- **nothing happens at all** → the characters are not reaching the front panel.
  Most likely Serial In is `IBASIC` with no program running, which is the
  normal state after a power cycle. Otherwise: a program hung inside a read
  (front-panel **Stop**, not Pause), or the link itself.

### The one safe automatic recovery

PROG when you wanted BAR: send `QUIT`. It answers `OK BYE` and *then* switches
Serial In back to `Inst`, so allow ~1 s after the reply before probing again.
That is the only clean way out of `IBASIC` mode from the wire.

It gets you half way and no further: `QUIT` restores Serial In but **cannot
restore the command-bar screen**, which is a front-panel action by construction
(§11). A client that reports "wrong baud or powered off" here is sending its
user to look in the wrong place for something that is working correctly.

---

## 4. Line framing and command grammar

One command per line, CR-LF terminated. The dispatcher, in order:

1. truncates the line at the first CR;
2. trims whitespace, keeping an **un-upper-cased copy** of the whole line and
   of the argument;
3. upper-cases the line for keyword matching;
4. an empty line is ignored with no reply;
5. splits at the first space: keyword (first 20 characters at most), argument
   (the rest, trimmed);
6. parses up to **three** whitespace-separated numbers out of the argument. A
   token that is not a number is skipped and does not count, so
   `FAST -60 rubbish` is read as a one-argument `FAST`.

### Hard limits, from the program's own `DIM` statements

Exceed these and you are in undefined territory — a string overflow has killed
the running program before.

| Limit | Value |
|---|---|
| whole command line | **80 characters** |
| keyword | 20 characters |
| argument | 80 characters |
| numeric arguments parsed | **3** |
| `AFCMD` argument (the AF query string) | **40 characters** |
| `PORT` argument | **10 characters** |
| `SCPIQ` answer field | 80 characters |
| points buffered for the fit | **300** |

The 80-character line limit is the one to watch when tunnelling SCPI: a long
command plus its quoted argument can reach it.

**Keywords are case-insensitive. Arguments are upper-cased too**, except for
`SCPI`, `SCPIQ`, `AFCMD` and `PORT`.

---

## 5. The command set

Taken from `SELECT W$` in `SINADCTL.BAS`. An unknown keyword answers
`ERR UNKNOWN <KEYWORD>`.

### Session and identity

| Command | Argument | Reply | Notes |
|---|---|---|---|
| `PING` | — | `OK SINADCTL <version>` | liveness probe. Same literal as the `READY` line since 2.3 — **see §12 for why that is not a given** |
| `HELP` | — | four `OK …` lines listing the keywords | |
| `STATUS` | — | three `OK …` lines | freq, dev, PL / level, offset, last 12 dB result / AF level, target, query |
| `QUIT` | — | `OK BYE` | turns RF off, restores Serial In = `Inst`, then `STOP`s the program |

### Configuration (all reply `OK <KEYWORD> <value(s)>`)

The "default" column is the **program's own value at startup**, read off its
initialisation block — not what the Python client happens to be configured
with. A client that cares should send every setting it depends on and read the
confirmation, which is what `sinad.py measure` does on every run. Note in
particular that
the program starts at **146.52 MHz**, which is the national FM simplex calling
frequency and the wrong thing to radiate a test tone on; send `FREQ` before
turning RF on.

| Command | Argument | Default | Effect |
|---|---|---|---|
| `FREQ` | MHz | 146.52 | sends `CONF:RFD 'Freq'`, then `RFG:FREQ` **and** `RFAN:FREQ` — the analyser always follows the generator |
| `DEV` | kHz | 3 | FM deviation of the test tone (`AFG1:FM`) |
| `TONE` | Hz | 1000 | modulating tone (`AFG1:FREQ`) |
| `PL` | Hz [devHz] or `OFF` | off, 600 Hz | sub-audible tone on AFG2 |
| `PORT` | `Dupl` or `RF Out` | `Dupl` | `RFG:OUTP`. **Case-preserved**, ≤10 chars |
| `OFFSET` | dB | 0 | added to levels **in reports only** (cable/pad loss, normally negative) |
| `AVG` | n ≥ 1 | 8 | readings averaged per fine point |
| `AVGC` | n ≥ 1 | 3 | readings averaged per coarse point |
| `SETTLE` | s | 0.3 | wait after each level change |
| `MAXLVL` | dBm | −30 | the generator is never set above this |
| `TARGET` | dB | 12 | SINAD target |
| `WIN` | above [below] | 6, 4 | fine-sweep window around the estimate, dB |
| `FSTEP` | dB | 0.5 | fine step |
| `SSTEP` | dB | 5 | coarse/sparse step; 0 disables |
| `BRACKET` | dB | 2 | bisection stops at this bracket width |
| `TAIL` | `ON`/`1` else off | on | also take coarse points *below* the fine window |
| `SCREEN` | `KEEP` else normal | normal | `KEEP` stops `SETUP` selecting screens. **Readings then return nothing** — §11 |
| `TRIG` | `ON`/anything else | off | `TRIG:MODE:RETR SING` + a `TRIG:IMM` before every read. Reply adds ` ERRS <n>` |
| `AFTGT` | volts [tol] | 1.0, 0.1 | AF level target and accept band |
| `AFCMD` | query string | `MEAS:AFR:ACL?` | overrides the AF-level query. **Case-preserved**, ≤40 chars. Bare `AFCMD` just reports it |
| `AFSC` | factor | 1 | multiplies the raw AF reading to get volts; 0 is coerced to 1 |

### Generator control

| Command | Argument | Reply | Notes |
|---|---|---|---|
| `LEVEL` | dBm | `OK LEVEL <dbm>` | clamped to `MAXLVL` **silently** — read the reply to see what you got |
| `RF` | `ON` / anything else | `OK RF <arg>` | `ON` also re-applies the level |
| `UNCAP` | — | `OK MAXLVL <dbm>` | probes the generator's real ceiling (as `RFLIM`) and raises `MAXLVL` to it. A deliberate act: see the warning below |
| `RFLIM` | — | `RFLIM,<lo>,<hi>,<port>` then `END` | asks the generator its own output range, without changing `MAXLVL` |

> `MAXLVL` is the only thing between a sweep and the generator's full output.
> *Measured on this unit:* the ceiling on `Dupl` is **+17.96 dBm** — 63 mW,
> which is a low-power transmitter, not a signal-generator level, and will
> destroy a receiver front end expecting microvolts. Never raise the cap by
> default.

### Measurement

| Command | Argument | Emits | Terminal |
|---|---|---|---|
| `READ` | — | one `PT` (phase `R`) | `END` |
| `FIND` | [hi [lo]] dBm | `PT` lines (phases `C`, `B`), then `BRACKET` | `END` |
| `FAST` | [hi [lo]] dBm | `PT` (`C`, `B`, `S`, `F`), `BRACKET`, `RESULT` | `END` |
| `SWEEP` | [hi [lo [step]]] dBm | `PT` (`L`), `RESULT` | `END` |
| `SETUP` | — | `OK SETUP` or `ERR SETUP <n> INSTRUMENT ERRORS` | — |
| `AFLVL` | [n] | `AFL,…` | — |
| `AFPROBE` | — | two `AFP,…` lines | `END` |

**`FIND` and `FAST` remember their range arguments**: the hi/lo you pass become
the defaults for the next bare `FIND`/`FAST` and for the front-panel USER keys.
`SWEEP` is different — it *reads* those remembered values when you omit an
argument but does not update them.

`SWEEP` also stops early once **three consecutive points read below 3 dB
SINAD**, so a sweep to −135 dBm usually ends above its stop level and you get
fewer points than `(hi−lo)/step`.

### Pass-through

| Command | Argument | Reply |
|---|---|---|
| `SCPI` | one SCPI command | `OK SCPI <errcount>`, plus `SCPIE,…` if non-zero |
| `SCPIQ` | one SCPI query | `SCPIQ,<echo>,<answer>`, plus `SCPIE,…` if non-zero |

Both answer `ERR SCPI NEEDS A COMMAND` / `ERR SCPIQ NEEDS A QUERY` with no
argument.

> **The parent's `README.md` also lists `AFSEL` and `AFSTR`.** Those commands **do not
> exist** in 2.3. They were removed once `MEAS:AFR:ACL?` turned out to be an
> always-live field rather than one of the `MEAS:AFR:SEL` choices, so nothing
> ever needed to switch the analyser. That README's serial-command list and
> the protocol paragraph in `CLAUDE.md` are both stale on this point; the
> dispatch is the authority.

---

## 6. The reply grammar

Every reply is one line. There are two shapes: **word-prefixed** status lines
(`OK` / `ERR` / `WARN`, space-separated) and **comma-separated data records**
(`PT,` `BRACKET,` `RESULT,` `AFL,` `AFP,` `RFLIM,` `SCPIQ,` `SCPIE,`). `END` is
a line of its own.

A client should classify on the prefix and ignore unknown prefixes rather than
erroring: the program writes human-readable text to the instrument's own screen
too, and future versions may add records.

### Status lines

| Line | Meaning |
|---|---|
| `OK SINADCTL <ver> READY` | sent once, at startup, after `RUN`. **This is the version to trust** |
| `OK SINADCTL <ver>` | answer to `PING` |
| `OK BYE` | answer to `QUIT`; Serial In switches to `Inst` *after* this line |
| `OK <KEYWORD> <values>` | a setting took; the values are what is now in force |
| `OK SETUP` | the setup sequence produced no instrument errors |
| `OK SCPI <n>` | a tunnelled command ran; `<n>` instrument errors followed |

### Errors — `ERR`

| Line | When |
|---|---|
| `ERR UNKNOWN <KEYWORD>` | the keyword is not in the dispatch |
| `ERR SETUP <n> INSTRUMENT ERRORS` | `SETUP` ran but the instrument complained `<n>` times; the `WARN` lines just before carry the records |
| `ERR HIGHLVL,<dbm>,<sinad>` | the climb reached `MAXLVL` without the target. `<dbm>` is the level reached, `<sinad>` the SINAD there. **Not terminal** — see below |
| `ERR SINAD AT LOW LEVEL STILL ABOVE TARGET` | even the bottom of the range is above the target, so there is nothing to bracket |
| `ERR SCPI NEEDS A COMMAND` / `ERR SCPIQ NEEDS A QUERY` | missing argument |

> **`ERR HIGHLVL` is a mixed-shape line** — a word prefix followed by a
> comma-separated payload. It is also **not terminal**: the program then offers
> the choice at the instrument's own softkeys and **waits up to 15 s**, after
> which it either climbs again (more `PT` lines) or returns and emits `END`. A
> client must keep reading.
>
> Older builds emitted the prose form `ERR SINAD AT HIGH LEVEL NOT ABOVE
> TARGET` instead. `sinad.py` recognises `HIGHLVL`, which is all a new client
> needs.

### Warnings — `WARN`

Never terminal. All of them are diagnoses, not failures.

| Line | Meaning |
|---|---|
| `WARN <error record>` | one record from the instrument's error queue, verbatim, e.g. `-200,"Execution error;Entry choice does not exist"` |
| `WARN ERRQ OUT OF STEP: <reply>` | the error queue answered with something that is not an error record, i.e. the output queue is serving an earlier query's answer. The program has issued a device clear; see §10 |
| `WARN ERRQ TIMEOUT` | the error queue did not answer; device clear issued |
| `WARN RAISING START TO <dbm> DBM` | the top of the range did not clear the target, so the climb is stepping up 20 dB |
| `WARN FIT NEEDS 3 POINTS NEAR TARGET, HAVE <n>` | no `RESULT` will follow |
| `WARN FIT SLOPE TOO SMALL` | the fitted slope is ≤ 0.2 dB/dB, so no crossing is reported. No `RESULT` will follow |
| `WARN UNCAPPED TO <dbm> DBM` | the cap was raised to the generator's measured ceiling |
| `WARN NO HEADROOM, CEILING <dbm> DBM` | the cap was already at the ceiling, so raising it changed nothing |

### Data records, field by field

**`PT,<phase>,<gen_dbm>,<sinad_db>,<n>,<sd>`** — one measured point, sent **as
it is measured**, so a client can plot live.

| Field | Meaning |
|---|---|
| `phase` | one of `C B S F L R`, expanded below |
| `gen_dbm` | the **generator setting**, 2 dp. `OFFSET` is *not* applied — add it yourself if you want the level at the fixture |
| `sinad_db` | mean of the valid readings, 2 dp. **`-999` means no reading was valid** — test for `≤ -998` |
| `n` | how many of the requested readings were valid (0 … `AVG`) |
| `sd` | sample standard deviation of those readings, 3 dp. **`-1` means fewer than two valid readings**, so test for `< 0` rather than parsing it as a number |

| Phase | Means |
|---|---|
| `C` | check — the endpoint probes, and any climb steps |
| `B` | bisect |
| `S` | sparse/coarse, above the fine window and (with `TAIL` on) below it |
| `F` | fine sweep |
| `L` | linear (`SWEEP`) |
| `R` | a single `READ` |

The sixth field (`sd`) arrived in SINADCTL 1.2. **Parse the first five and
treat the sixth as optional**, so a five-field line from an older program still
works.

**`BRACKET,<lo>,<hi>`** — generator dBm, 2 dp. Emitted by `FIND`/`FAST` only
when the bisection succeeded; its absence is itself information.

**`RESULT,<gen_dbm>,<dbm_with_offset>,<uV>`** — the fitted crossing. Field 2 is
field 1 plus `OFFSET`; field 3 is that level expressed as microvolts PD into
50 Ω, 3 dp. The fit is a least-squares line through the non-`B`, non-`C` points
whose SINAD lies between `TARGET−5` and `TARGET+7` dB, and it needs at least
three such points.

**`AFL,<volts>,<n>,ACL,<sd>`** — an averaged AF level. Five fields.

| Field | Meaning |
|---|---|
| `volts` | the mean reading **already multiplied by `AFSC`**, 4 dp. **`-1` means no valid reading** |
| `n` | valid readings |
| `ACL` | a literal tag naming what the analyser was read for. **Reject any reading not tagged `ACL`** — it is not a voltage |
| `sd` | sample standard deviation, 4 dp; `-1` if fewer than two |

**`AFP,<query>,<value>,OK`** / **`AFP,<query>,,ERR`**, then
**`AFP,UNITS,<units>,OK`** / **`AFP,UNITS,,ERR`**, then `END` — the `AFPROBE`
result. *Measured on this unit:* the units come back `V`, so `AFSC` stays 1.

**`RFLIM,<lo>,<hi>,<port>`**, then `END` — the generator's own range in dBm,
2 dp, and the output port the limits apply to (they depend on it).

**`SCPIQ,<echo>,<answer>`** — the tunnelled query result. §2 explains why you
must check the echo. A line with **no second comma** means the program predates
1.6 and cannot tell you which query it answered; treat that as unusable and
reload it.

**`SCPIE,<echo>,<error record>`** — follows an `OK SCPI` or `SCPIQ` line when
the instrument complained. The record is the instrument's own words, which is
what turns "HP-IB error" into `Entry does not exist in menu [RFAN:SQU?]`.

### What is terminal

`END` is emitted by **`READ`, `FIND`, `FAST`, `SWEEP`, `AFPROBE` and `RFLIM`**,
and by nothing else. Settings, `SETUP`, `PING`, `STATUS`, `AFLVL`, `SCPI` and
`SCPIQ` complete with their own reply line and send no `END`.

So: for the six commands above, read until `END` or your own overall timeout.
For everything else, read until the expected prefix arrives, logging any
`WARN`/`ERR` lines that turn up on the way.

### The trap: the program does not read serial during a run

`ENTER 9` happens **only in the main idle loop**. During `FAST`, `SWEEP`,
`FIND` or `READ` the program never looks at the port, so anything you send is
buffered by the UART and acted on **after** the run finishes.

Practical consequence: there is **no abort**. An `RF OFF` sent mid-sweep takes
effect when the sweep ends, not when you send it. A client that wants to stop a
run early has two options, both outside the protocol: wait for `END`, or stop
the program at the front panel. Do not claim to have stopped the generator when
you have only queued a command.

---

## 7. A worked exchange

`→` is laptop-to-8935, `←` is 8935-to-laptop. Every line is CR-LF terminated;
NUL padding on inbound lines is not shown.

**Precondition:** the program is already running (state PROG). If it is not,
see §8.

```
# 1. Is it alive, and which build?
→  PING
←  OK SINADCTL 2.3                 (same literal the READY line sends)

# 2. Configure. Each setting answers; read the answer, do not assume.
→  FREQ 145.55
←  OK FREQ 145.55
→  DEV 3
←  OK DEV 3
→  TONE 1000
←  OK TONE 1000
→  OFFSET -34.5
←  OK OFFSET -34.5
→  MAXLVL 0
←  OK MAXLVL 0
→  TARGET 12
←  OK TARGET 12
→  AVG 8
←  OK AVG 8
→  AVGC 3
←  OK AVGC 3
→  SETTLE .3
←  OK SETTLE .3

# 3. Apply the generator + AF analyser setup.
→  SETUP
←  OK SETUP                        (or: WARN lines, then ERR SETUP n ...)

# 4. Set the audio chain through the tunnel, then READ IT BACK.
#    Sending a setting is not evidence it took (§11).
→  SCPI AFAN:FILT1 '50HZ HPF'
←  OK SCPI 0
→  SCPI AFAN:FILT2 '3kHz LPF'
←  OK SCPI 0
→  SCPI AFAN:DEMP 'Off'
←  OK SCPI 0
→  SCPIQ AFAN:FILT2?
←  SCPIQ,AFAN:FILT2?,"3KHZ LPF"    (echo matches - accept)
→  SCPIQ AFAN:DEMP?
←  SCPIQ,AFAN:DEMP?,"OFF"

# 5. Confirm the instrument agrees about the state the run will use.
→  SCPIQ RFG:FREQ?
←  SCPIQ,RFG:FREQ?,+1.45550000E+008
→  SCPIQ CONF:RFD?
←  SCPIQ,CONF:RFD?,"FREQ"          (if this is not Freq, RFG:FREQ was ignored)
→  SCPIQ MEAS:AFR:SEL?
←  SCPIQ,MEAS:AFR:SEL?,"SINAD"

# 6. Optional: match the radio's audio level. Poll and prompt.
→  AFLVL 3
←  AFL,0.9269,3,ACL,0.0041         (tagged ACL - usable; 0.93 V)

# 7. The sweep. One line in, a stream of records out.
→  FAST -60 -135
←  PT,C,-60.00,1.56,3,0.917
←  PT,C,-40.00,31.49,3,0.161
←  PT,C,-135.00,1.78,3,0.640
←  PT,B,-87.50,1.57,3,0.651
←  PT,B,-63.75,1.69,3,1.145
←  PT,B,-51.87,5.77,3,1.561
←  PT,B,-45.94,24.51,3,0.778
←  PT,B,-48.91,12.14,3,0.901
←  PT,B,-50.39,9.40,3,1.028
←  BRACKET,-50.39,-48.91
←  PT,F,-43.65,28.64,8,0.571
←  PT,F,-44.15,29.13,8,0.691
         ... fine points every 0.5 dB through the crossing ...
←  PT,S,-57.00,1.62,3,0.430
         ... coarse tail down to the stop level ...
←  RESULT,-52.50,-87.00,530.293
←  END

# 8. Leave it safe.
→  RF OFF
←  OK RF OFF
```

Step 7's figures are from a real run
recorded by the full tool in the parent directory, which is why the levels are
so high: that radio was being measured through a radiating coupling path at an
RF-noisy site. Step 6's voltage is from the same run; the spread digit beside
it is illustrative, since the per-reading spread was not kept. Everything else
in the transcript is the format, not data. (Step 6 is also not something the
programs in this folder do — the volume step is one of the things `minimal/`
leaves out — but `AFLVL` is a real command and `sinad.py term` can send it.)

**Minimum viable client**, in outline:

```python
send("PING");  expect_prefix("OK SINADCTL", timeout=3)
for setting in settings:
    send(setting); expect_prefix("OK", timeout=10)
send("SETUP");  expect_prefix(("OK SETUP", "ERR SETUP"), timeout=60)
send("FAST -60 -135")
rows, result, deadline = [], None, now() + 900
while now() < deadline:
    line = readline(0.1)          # strip \r and \x00
    if line is None:      continue
    if line == "END":     break
    if line.startswith("PT,"):      rows.append(parse_pt(line))
    elif line.startswith("RESULT,"): result = line.split(",")[1:4]
    elif line.startswith("BRACKET,"): pass
    elif line.startswith(("ERR", "WARN")): log(line)   # never fatal on its own
send("RF OFF"); expect_prefix("OK RF", timeout=10)
```

Note what is *not* in that loop: no abort, no per-point timeout (a long gap is
normal — see `ERR HIGHLVL`), and nothing treats a `WARN` as a failure.

---

## 8. Loading the program over the same wire

`load.py` in this folder does all of this; you need the detail only if you
are replacing it. The problem: get ~730
numbered BASIC lines into the instrument when the only thing the serial port
can do in `Inst` mode is type onto the command bar, at roughly **2 s per typed
line**.

Two stages. Stage 1 types a 31-line receiver program; stage 2 streams the real
program into a RAM file at full rate.

### Preparing the source

- Keep numbered lines' numbers; number unnumbered lines from 10 in steps of 10.
- **Drop blank and comment-only lines.** Every line costs 2 s typed and 0.08 s
  streamed.
- Each line must be ≤ 80 characters (the IBASIC limit the static checker
  enforces).

### Stage 1

State must be **BAR**. Clear the bar (§3), then type, paced at 10 ms per
character. Between lines, wait for the echo to go quiet — up to ~4 s, with
"quiet" meaning ~0.4 s without a new character — and fall back to a flat ~2 s
per line if the instrument is not echoing at all:

```
(blank line)
SCRATCH
MSI ":MEMORY,0,0"            ─┐ only when freeing the stored copy first,
PURGE "SINADCTL"             ─┘ which is normally required - see sizing
<the 31 lines of SERLOAD.BAS, with line 90's record count rewritten>
RUN
```

`SERLOAD`, in order: `MSI` the RAM disc · `PURGE "SNDTMP"` under an error trap
· `CREATE ASCII "SNDTMP",<recs>` · `ASSIGN @F` ·
`OUTPUT 800;"CONF:SPOR9:SIN 'IBASIC'"` ← **the hand-off: from here your bytes
are program input, not keystrokes** · `OUTPUT 9;"LOADER READY"` · read one
line, write it, answer `LOADER FIRST <line>` · loop `ENTER 9` → `OUTPUT @F`
under `ON TIMEOUT 9,5 GOTO Done` · close · `CONF:SPOR9:SIN 'Inst'` ←
**hand-back** · `OUTPUT 9;"LOADER DONE <count>"`.

Then wait up to 30 s for:

```
←  LOADER READY
```

No `LOADER READY` means the loader did not get that far. Read the ERROR code
off the 8935's screen — almost always **ERROR 64** at line 90 (no room) or
**ERROR 54** (a leftover `SNDTMP`). Nothing has been streamed.

### Sizing the RAM file

`CREATE ASCII` needs a record count, and **a fixed number is wrong**: 80 was too
small (ERROR 59, and the write fails a minute into the stream) and 200 too big
for the disc (ERROR 64, at `CREATE`). Compute it from the program and rewrite
the number in the loader's `CREATE ASCII` line as you type it:

```
need = Σ (len(line) + 2) + 2 × line_count      bytes
recs = ceil(need / 256) + 8                    256-byte records
```

Context, *measured* with `CAT ":MEMORY,0,0"`: the stored program is **167
records** of 256 bytes (42,752 bytes — about double its ASCII source, which is
what tokenising does) starting at record 85, so the volume is at least 252
records and roughly 85 are free. The transfer file needs ~94. **Both copies do
not fit.** Hence the ordering that makes it work:

1. `PURGE` the stored program **before** `CREATE` (peak use 94, not 261);
2. `PURGE "SNDTMP"` after `GET`, **before** `STORE`.

The cost is that a failed load leaves nothing stored — acceptable, since the
source is on your machine either way.

### Stage 2

1. **Enable XON/XOFF** on your port. The loader throttles the stream itself.
2. Send **program line 1 alone** and wait up to 12 s for
   `LOADER FIRST <line>`. Compare it with what you sent.
   - no answer → the loader is running (it said `LOADER READY`) but nothing
     came back from the write, so the RAM file is the suspect: `INITIALIZE`
     `:MEMORY,0,0` at the front panel. Nothing streamed.
   - different line → characters are being lost or reordered; raise the
     character delay, then the stream delay. Nothing streamed.

   This preflight exercises serial out, the running loader, the file, the write
   and serial back **before** committing the minute the rest takes.
3. Stream lines 2…N, **one every 0.08 s**. *Measured:* 0.02 s fails — the
   stream completes in 15 s, the loader never reports a count and the program
   never starts. Nothing between 0.02 and 0.08 has been tested.
4. **Disable XON/XOFF.** Wait up to 15 s for the 5 s read timeout to fire
   inside the loader and the file to close:

   ```
   ←  LOADER DONE 731
   ```

5. **Compare that count with the number of lines you sent.** This is the only
   evidence the stream arrived intact. If it is missing or short, **do not
   store** — storing purges the last known-good program first, so a bad stream
   would replace a working program with a truncated one that loads without
   complaint and misbehaves later. Raise the stream delay and start again.

### Finishing

Serial In is back to `Inst`, so you are typing onto the bar again:

```
GET "SNDTMP"
```

**Then wait for the bar to prove it is listening** before typing anything else:
type `PRINT 1+90134` and wait for `90135`. *Measured:* `GET` of a 700-line
program takes longer than 3 s, so an `MSI` and `PURGE` typed straight after it
went into a busy bar and were never seen — while `STORE`, arriving six seconds
later, landed and overflowed the volume. Nothing reported an error, because
nothing had failed.

```
MSI ":MEMORY,0,0"
PURGE "SNDTMP"               (ERROR 56 here is fine - see below)
MSI ":MEMORY,0,0"
PURGE "SINADCTL"             (ERROR 56 here is fine)
STORE "SINADCTL"
RUN
```

Then wait up to 30 s for `OK SINADCTL <ver> READY`, and **check the version**:
what was stored may predate your source, and a stale build starts silently.

### Instrument error codes you will meet

| Code | Meaning | What to do |
|---|---|---|
| **ERROR 5** | improper context terminator | a `GOSUB` target sits after `END` in the source |
| **ERROR 54** | duplicate file name | `STORE` refuses to overwrite. `PURGE` first — otherwise a later `--start` silently loads a stale build |
| **ERROR 56** | file name is undefined | the file is not there, which is the state a `PURGE` exists to reach. **Tolerate exactly 56 on a `PURGE` and report every other code** |
| **ERROR 58** | improper file type | `GET` on a `STORE`d program. `STORE` writes `IBPRG`; `GET` is for ASCII. Use `LOAD` |
| **ERROR 59** | — | the transfer file was created too small; the write runs off the end a minute into the stream |
| **ERROR 64** | mass storage overflow | no room for `CREATE`. `PURGE` something, or `INITIALIZE` the volume |

### Starting a stored program without the loader

Three typed lines, a few seconds instead of a minute and a half:

```
MSI ":MEMORY,0,0"
LOAD "SINADCTL"
RUN
```

`LOAD`, not `GET` (ERROR 58). *Measured:* the RAM disc is battery-backed on this
unit and survives a power cycle, so this is the routine startup. If the program
is merely stopped rather than lost, the IBASIC Controller screen's `Run`
softkey restarts it from line 10 and it re-sets Serial In itself.

---

## 9. Timing and timeouts a client must allow

**The rule that has caused two bugs that looked like hardware faults: your
timeout must exceed the instrument's worst case, computed rather than guessed.**
Both halves of this table matter, because a timeout that is too short loses a
reply that was coming — and an abandoned reply then poisons the *next* read
(§10).

### Inside the program (these set the worst cases)

| Guard | Value | Effect |
|---|---|---|
| main idle loop | `ON TIMEOUT 9,1` | the port is re-read every second while idle |
| every bus read | `ON TIMEOUT 8,5` | a query that is never answered costs 5 s and yields the "no reading" sentinel, not a hang |
| error-queue read | `ON TIMEOUT 8,2`, up to 3 records | so `Chk_err` alone can take ~6 s |
| `SCPIQ` answer | `ON TIMEOUT 8,3` | plus the `Chk_err` that follows it |
| `AFLVL n` | n × 5 s worst case | it still replies, with `n=0` |
| the climb-to-cap prompt | 15 s | silence after `ERR HIGHLVL` is normal |

### What to allow from your side

| Operation | Allow | Why |
|---|---|---|
| `PING` | 3 s | one line, no bus traffic |
| a setting (`FREQ`, `AVG`, …) | 10 s | some send bus commands |
| `SETUP` | 60 s | ~17 bus writes plus an error-queue read |
| `SCPIQ` | **20 s**, and retry once on an echo mismatch | computed worst case is ~9 s (3 s for the answer + up to 3×2 s of `Chk_err`) plus device clears. 20 s is what the existing client allows, deliberately with margin — the previous 12 s was overrun and *that* is what desynchronised the queue |
| `AFLVL n` | **5·n + 6 s** | the measured trap: the old `max(15, 4+2n)` was exactly 15 s against a 15 s worst case at n=3, so one slow read lost the reply and the step reported "No AF reading" for a chain that was working |
| `FAST` / `SWEEP` overall | **900 s** | generous on purpose; see below |
| after `ERR HIGHLVL` | **≥ 20 s** of silence before concluding anything | the prompt is waiting at the instrument |
| stage-1 `RUN` → `LOADER READY` | 30 s | |
| preflight line → `LOADER FIRST` | 12 s | |
| stream end → `LOADER DONE` | 15 s | the loader's own 5 s read timeout has to fire first |
| `RUN` → `OK … READY` | 30 s | |

### Measured run times

*Measured* across 38 real-radio runs, from the timestamps the full tool
records with each point (the programs here print the points and keep no file):

| | |
|---|---|
| a whole `FAST` run, 41–48 points | **48–56 s** (median 50 s) |
| interval between fine points | **1.18–1.23 s** |
| implied `MEAS:AFR:SINAD?` round trip | **~90 ms** |

A fine point is `SETTLE` (0.3 s) + 2 discarded reads + `AVG` reads = 10 bus
queries; a coarse point is 5. A default `FAST` run is ~40 points, so ~305
SINAD queries and 12 s of accumulated settle.

*The load-bearing assumption in the 90 ms figure is that the per-point interval
is dominated by the queries and the settle, and not by level setting or the
instrument's own housekeeping.* It is arithmetic from logged timestamps, not a
timing loop, and a direct measurement would be better. Do not build a tight
per-point timeout on it; 10 s per point is safe and costs nothing.

**Is the averaging real?** Only if consecutive queries re-trigger. *Measured*
across those same 38 runs: per-run median spread **0.44–1.29 dB** and **0 of
1611 points** came back below 0.005 dB, so they do re-trigger and `AVG` is
doing real work. If you ever see zero spread everywhere, `AVG 1 AVGC 1` costs
nothing and `TRIG ON` is the documented fix (p346) — **untested on hardware**,
and if the query does not block until the triggered measurement completes it
would return stale data while appearing fresh.

---

## 10. Error-queue discipline on bus 800

This is where a whole bench day went, so it is worth understanding before you
write any readback code.

**Every `SCPIQ` is two bus transactions**: the query, then `SYST:ERR?`. Any read
that times out leaves its request unanswered on the bus. That answer then comes
back as the **next** read's result, so the entire readback lags by one query and
reports a screenful of plausible, wrong state.

Four rules follow, all *measured*:

1. **`*CLS` is not a fix.** IEEE 488.2 has `*CLS` clear the error queue and the
   status byte, **not the output queue**. That needs a **device clear** — HP
   BASIC's `CLEAR 800`, which is accepted on this unit. An orphaned response
   survives `*CLS`, survives `QUIT`, and survives reloading the program.
   *Measured:* a stale `"30 KHZ"` left from one session's `RFAN:IFBW?` came
   back in the *next* session as a reported instrument error.
2. **Never drain by reading.** Reading a bus with nothing to send provokes
   `-420 Query UNTERMINATED`, which the 8935 *displays* — so a pre-query drain
   announces itself on the instrument's screen on every single query. The
   routine that did this was deleted in favour of a device clear, which
   provokes nothing.
3. **Discard your own buffer before each query.** Anything already buffered on
   your side is the tail of a query you gave up on. Reading it as this query's
   answer is exactly what made each abandoned query poison its successor — and
   because the old retry re-sent rather than discarded, **the lag grew**: 1, 1,
   2, 2, 3…
4. **Check the echo, retry once.** With the echo (§2) a slipped answer is
   visible rather than silent, and reading it puts the queue back in step, so
   asking again recovers at the cost of one query.

For completeness, what the program already does for you, and what you will see
when it does:

| Situation | Program's action | Line you see |
|---|---|---|
| error queue answers with a non-error record | device clear + `*CLS` | `WARN ERRQ OUT OF STEP: <reply>` |
| error queue does not answer | device clear + `*CLS` | `WARN ERRQ TIMEOUT` |
| `SCPIQ` answer times out | device clear + `*CLS`, then replies with an empty answer field | `SCPIQ,<echo>,` |
| real instrument errors | reports up to 3 records | `WARN <record>` each, then `SCPIE,…` |

A device clear is also issued at startup, which is why the first readback of a
session is clean where every earlier attempt produced fragments.

**One exception to reporting:** `RFLIM` deliberately asks for levels it expects
to be refused, so each rejection puts a `-200 Execution error` in the queue.
The errors *are* the measurement there, not a fault, so the program counts them
without reporting them for the duration of the probe. Do not be surprised by
`RFLIM` being quiet.

---

## 11. SCPI rules that actually apply on this instrument

Four rules matter more than any individual command, and all four were worked
out the hard way.

### The screen must be displayed — for readings, not for settings (p205)

The `DISPlay` subsystem's own words: "A screen should be displayed before a
measurement from that screen is made." Each command page names its
"Screen/field equivalent", and a field not in the current menu is rejected with
**"Entry does not exist in menu"** — a *menu* error, not a syntax error
(`-113 Undefined header` is the syntax one).

**Confirmed on this unit, 2026-10-08, and the wording is exact:**

- **Settings go through from any screen.** `RFAN:INP`, `RFAN:FREQ`, `RFAN:SQU`
  and the whole AF chain all took with a different screen displayed, and read
  back correctly.
- **Measurements do not.** On that same run `MEAS:AFR:ACL?` returned **zero
  valid readings**, because AF ANALYZER was not displayed.
- **The check happens at measurement time, not at setup time.** *Measured:*
  navigating to another screen mid-run made the measurement **pause**. So it is
  not that a setup sequence must *end* on the right screen — the screen has to
  be displayed at the moment of each reading, which also means somebody walking
  up and changing the screen breaks a run.

Which screen a command belongs to: `RFG:*` → RF GENERATOR · `RFAN:*` → RF
ANALYZER · `AFAN:*` and `MEAS:AFR:*` → AF ANALYZER.

Practical rule for a client: select AF ANALYZER and leave it there for the
duration of a sweep. The 8935 can show its own running SINAD line, **or** it
can take readings — not both.

### Real Number Setting Syntax (p299)

Any command documented as using it **also accepts** `:STATe 1|ON|0|OFF` and
`:STATe?` (which returns 1 or 0), plus `:DUNits :UNits :INCRement :MODe
:MULTiply :DIVide` — none of which are indexed in the contents. So
`RFG:AMPL:STAT ON` is valid even though the contents lists only
`RFGenerator:AMPLitude`. **The per-command pages are authoritative; the
contents listing is not.**

**The one documented exception is `RFG:FREQ`**, where p310 says `:STATe` is
*not* valid.

### `OK SCPI 0` is not evidence a command took effect

*Measured, and this is the nastiest property on the box:* **`DISP` accepts an
undocumented screen name silently and ignores it.** Sending `DISP TIB` reported
no error at all, produced no error-queue entry — and the screen did not change.

So a zero error count means "nothing was rejected", not "it worked". **Anything
that changes the answer must be read back.** That has cost three separate bugs,
and it is why the AF chain and the generator frequency are both read back after
being set.

Two specific traps in the same family:

- **`RFG:FREQ` is ignored outright in channel tuning mode** (p310: "The Test
  Set must first be in frequency tuning mode"), silently. Send
  `CONF:RFD 'Freq'` first, and read `CONF:RFD?` back to prove it took.
- **`SETUP` resets `AFAN:INP` to `'Audio In'`.** Set the AF input *after*
  `SETUP`, never before — otherwise an `AFAN:INP 'FM Demod'` is silently undone
  and `MEAS:AFR:FM?` then answers **empty**, because with Audio In selected
  there is no demodulator in the path.

### The documented choice lists do not all match this unit

`-200,"Execution error;Entry choice does not exist"` means **the argument value
is not one of that field's choices** — nothing to do with screens or menus.

*Measured:* `RFAN:IFBW '15 kHz'` is **rejected**, and the same instrument
answers `RFAN:IFBW?` with `"30 KHZ"`. The command dictionary lists only
`'15 kHz'` and `'230 kHz'` for that field. `9018-70126.pdf` covers a family and
the IF filter is one place this unit differs.

**Treat the instrument's own readback as the authority and the manual as a
starting point.** Read the choice list off the front-panel field before setting
anything the readback contradicts.

### Strings on the wire

Single-quote them and use the manual's exact case: `'Audio In'`, `'Dupl'`,
`'Inst'`, `'FM'`, `'C MESSAGE'`, `'50HZ HPF'`, `'3kHz LPF'`, `'750 us'`,
`'RMS'`, `'Auto'`, `'Gnd'`. *Measured:* the instrument **accepts** that mixed
case and **answers** in upper case, in double quotes. Whether it would also
accept the wrong case was never isolated, so matching the manual is correct
either way.

### `DISP?` answers `TIB` for a screen you cannot select

*Measured:* `DISP?` returns **`TIB`** for the IBASIC controller screen, which is
**not in p205's list** of `DISP` arguments — and `DISP TIB` does not work (see
above). **The IBASIC screen can be read but not set over the bus.**

That is why restoring the command bar is a front-panel action, permanently, and
why a client cannot recover state BAR on its own after a session that ran
`SETUP`. It is inherent, not a defect.

---

## 12. Quirks that will cost you an afternoon

**The version used to come from two literals, and they drifted.** In 2.0
through 2.2 the startup line said `OK SINADCTL 2.2 READY` while `PING`
answered `OK SINADCTL 1.9` — the same build, two strings, because the `PING`
literal was never updated. A client comparing the `PING` version against an
expected one therefore reported "the instrument is running an older build;
reload it" on *every* command of a correctly loaded program, which is how you
train people to ignore the message that matters.

Fixed in **2.3**: one `Ver$`, sent in both lines, and `check_bas.py` now fails
if a second version literal appears anywhere in the program. Two things follow
for a client:

- **Read the version out of whichever line the program sent**, and hold it in
  one place of your own. Never write a second copy of the number.
- **If you are talking to a 2.0–2.2 build**, trust the `READY` line and ignore
  `PING`'s version. The difference is diagnostic: a `PING` answer of `1.9`
  from a program whose `READY` line said something else identifies the build
  range exactly.

**There is no abort.** See the end of §6.

**`LEVEL` clamps silently** to `MAXLVL`. The reply tells you what you actually
got; the request does not.

**`OFFSET` affects reports only.** `PT` lines carry the raw generator setting;
`RESULT` carries both. Nothing in the instrument changes when you set it.

**`FIND`/`FAST`/`SWEEP` arguments are sticky.** They become the defaults for
the next call and for the front-panel keys, so a client that passes a range
once has changed the state a later bare `FAST` will use.

**`SWEEP` self-terminates** after three consecutive points below 3 dB SINAD, so
you will usually get fewer points than `(hi-lo)/step`.

**A `WARN` is never fatal** and `ERR HIGHLVL` is not terminal. Only `END`, or
your own overall timeout, ends a measurement command.

**`QUIT` replies before it acts.** `OK BYE` arrives, *then* Serial In goes back
to `Inst`. Allow ~1 s.

**Serial In survives a power cycle**, so a reboot with the program running
leaves the link apparently dead (§3). `QUIT` before powering off.

**`PRINTER IS CRT` is pinned by the program on purpose.** `PRINT` output
otherwise goes wherever the PRINTER CONFIGURE screen points — possibly to
serial 9, the link you are driving it over.

---

## 13. What could not be established from the repo

Stated here rather than guessed at anywhere above.

- **Whether `ENTER 9` tolerates a line longer than 80 characters**, or how it
  fails. The limit is inferred from the program's `DIM` statements and from one
  bench incident where concurrent access produced a string overflow that killed
  the program. The *consequence* of overflow is therefore known to be bad; the
  exact boundary behaviour is not.
- **Whether the reply stream can be read reliably while a command is being
  sent.** Nothing in the repo does this, and the program only reads serial in
  its idle loop, so a client should treat the link as strictly
  request/response.
- **Whether quoted strings are matched case-sensitively** on bus 800. Matching
  the manual is correct either way, but the reason the old wrong-case strings
  failed was never isolated.
- **Whether `AFG1:DEST 'FM'` and `AFG2:DEST 'FM'` can be set simultaneously**
  (tone plus PL together). Both fields exist independently on the screen, which
  makes it plausible; the manual does not say.
- **`*CLS` itself is not in `9018-70126.pdf`** — that manual does not cover
  IEEE 488.2 common commands. Its behaviour here is unverified but not
  contradicted; its *inability* to clear the output queue is from the IEEE
  standard and was confirmed on the bench by a stale response surviving it.
- **Over-range behaviour of `MEAS:AFR:ACL?`** (a silently pegged number is the
  dangerous case), and whether the instrument's own averaging is enabled
  (`MEAS:AFR:SINAD:AVER:STAT?`). If it is, the per-point `sd` understates the
  real spread and the §9 conclusion about averaging needs qualifying.
- **`TRIG ON` / `TRIG:MODE:SETT FAST|FULL`** have never been run on hardware.
- **The per-query time** is arithmetic from logged timestamps, not a timing
  loop.
- **Whether an `ON KEY` branch is serviced from inside the `WAIT .1` loop** in
  the climb-to-cap prompt. The five USER softkeys themselves are confirmed on
  hardware (2026-10-11), serviced from the main idle loop; the front-panel
  **numeric keypad** is measured *unreachable* from IBASIC and is not an input
  path at all.
- **The serial connector's DTE/DCE pinout.**
- **Anything between `--stream-delay` 0.02 (fails) and 0.08 (works).**

---

How to use the two programs in this folder is in [`README.md`](README.md).
Operator-facing material — cabling, front-panel setup, what the measurement
means, desense, troubleshooting — plus the bench history behind every
*measured* claim here, is in the parent directory: `OPERATING.md`,
`CLAUDE.md`, and `MANUAL_VERIFICATION.md` for the command-by-command check
against the GPIB reference.
