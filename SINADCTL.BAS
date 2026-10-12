10 ! SINADCTL 2.3 - SINAD control for HP 8935 over serial
20 ! Commands arrive on serial port Sp; replies go back on Sp.
30 ! Test set is controlled on internal bus 800. Type HELP.
40 OPTION BASE 1
50 DIM Cmd$[80],W$[20],A$[80],B$[80],E$[80],Pc$[2],Oport$[10]
60 DIM Afq$[40],Q$[80],Qa$[80],Tg$[24],Sq$[80],Er$[80],E2$[80]
65 DIM Ln$[80],Nb$[20],Bl$[12],Ver$[8]
70 DIM Lv(300),Sn(300),X(3)
80 DIM Ph$(300)[2]
90 Sp=9 ! serial port select code (9 = command port)
100 Freq=146.52 ! MHz
110 Dev=3 ! kHz FM deviation of the 1 kHz tone
120 Tone=1000 ! Hz
130 Plf=0 ! PL tone Hz, 0 = off
140 Pld=600 ! PL deviation Hz
150 Lofs=0 ! dB added to levels in reports (cable/pad loss)
160 Navg=8 ! readings per fine point
170 Navgc=3 ! readings per coarse point
180 Ndisc=2 ! readings discarded after each level change
190 Settle=.3 ! s
200 Maxlvl=-30 ! never set the generator above this, dBm
210 Tgt=12 ! SINAD target, dB
220 Brk=2 ! bisection stops at this bracket width, dB
230 Fstep=.5 ! fine step, dB
240 Wa=6 ! fine window above estimate, dB
250 Wb=4 ! fine window below estimate, dB
260 Sstep=5 ! sparse step above window, dB (0 = off)
265 Tl=1 ! 1 = also take coarse points below the fine window, down to the stop
267 Scr=1 ! 1 = Setup selects the RFG then AFAN screens; 0 = leave the screen
268 Eq=0 ! 1 = Chk_err counts errors without reporting them
270 Hstart=-60 ! default high level, dBm
280 Lstop=-130 ! default low level, dBm
290 Oport$="Dupl" ! manual p312: 'RF Out' or 'Dupl'
300 Lvl=Hstart
310 Np=0
320 R12=-999
330 Trg=0 ! 1 = TRIG:IMM before each read (manual p346)
340 ! AF level. MEAS:AFR:ACL? (manual p211) reads the AC Level field, which
350 ! is always live when AFAN:INP is 'Audio In'. It is NOT one of the
360 ! MEAS:AFR:SEL choices, so reading it does not disturb SINAD.
370 Afq$="MEAS:AFR:ACL?" ! manual p211, CONFIRMED
380 Afsc=1 ! reading*Afsc = volts. Check with AFPROBE (reads :UNits?)
390 Aftgt=1 ! target AF level, volts rms
400 Aftol=.1 ! accept band, +/- volts
410 Afv=-1 ! last averaged AF level
412 Ver$="2.3" ! one literal: READY and PING must not drift apart
415 GOSUB Set_prt
420 GOSUB Init_ser
430 GOSUB Set_keys
440 OUTPUT Sp;"OK SINADCTL "&Ver$&" READY"
450 DISP "SINADCTL ready: serial commands or USER keys k1-k5"
460 Idle: ON TIMEOUT Sp,1 GOTO Idle
470 ENTER Sp;Cmd$
480 OFF TIMEOUT Sp
490 GOSUB Parse
500 GOTO Idle
510 !
520 Parse: P=POS(Cmd$,CHR$(13))
530 IF P>0 THEN Cmd$=Cmd$[1,P-1]
540 Q$=TRIM$(Cmd$) ! case preserved
550 Cmd$=UPC$(Q$)
560 IF Cmd$="" THEN RETURN
570 P=POS(Cmd$," ")
580 IF P=0 THEN
590   Lw=LEN(Cmd$)
600   IF Lw>20 THEN Lw=20
610   W$=Cmd$[1,Lw]
620   A$=""
630 Qa$=""
640 ELSE
650   Pw=P
660   IF Pw>21 THEN Pw=21 ! W$ is 20 chars; do not overflow it
670   W$=Cmd$[1,Pw-1]
680   A$=TRIM$(Cmd$[P+1])
690 Qa$=TRIM$(Q$[P+1]) ! case preserved arg
700 END IF
710 GOSUB Split
720 SELECT W$
730 CASE "PING"
740 OUTPUT Sp;"OK SINADCTL "&Ver$
750 CASE "HELP"
760   OUTPUT Sp;"OK PING SETUP FREQ DEV TONE PL PORT OFFSET AVG AVGC"
770   OUTPUT Sp;"OK SETTLE MAXLVL TARGET WIN FSTEP SSTEP TAIL SCREEN UNCAP"
780   OUTPUT Sp;"OK RF READ FIND FAST SWEEP STATUS QUIT"
790 OUTPUT Sp;"OK AFLVL AFTGT AFCMD AFSC AFPROBE TRIG RFLIM SCPI SCPIQ"
800 CASE "SETUP"
810   GOSUB Setup
820 CASE "FREQ"
830   Freq=X(1)
835   OUTPUT 800;"CONF:RFD 'Freq'" ! or RFG:FREQ is silently ignored
840   OUTPUT 800;"RFG:FREQ "&VAL$(Freq)&" MHZ"
845   OUTPUT 800;"RFAN:FREQ "&VAL$(Freq)&" MHZ" ! analyser follows the gen
850   OUTPUT Sp;"OK FREQ "&VAL$(Freq)
860 CASE "DEV"
870   Dev=X(1)
880   OUTPUT 800;"AFG1:FM "&VAL$(Dev)&" KHZ"
890   OUTPUT Sp;"OK DEV "&VAL$(Dev)
900 CASE "TONE"
910   Tone=X(1)
920   OUTPUT 800;"AFG1:FREQ "&VAL$(Tone)&" HZ"
930   OUTPUT Sp;"OK TONE "&VAL$(Tone)
940 CASE "PL"
950   IF A$="OFF" THEN
960     Plf=0
970   ELSE
980     Plf=X(1)
990     IF Na>1 THEN Pld=X(2)
1000   END IF
1010   GOSUB Set_pl
1020   OUTPUT Sp;"OK PL "&VAL$(Plf)&" "&VAL$(Pld)
1030 CASE "PORT"
1040 Oport$=Qa$ ! case preserved: the manual spells it 'Dupl'
1050   OUTPUT 800;"RFG:OUTP '"&Oport$&"'"
1060   OUTPUT Sp;"OK PORT "&Oport$
1070 CASE "OFFSET"
1080   Lofs=X(1)
1090   OUTPUT Sp;"OK OFFSET "&VAL$(Lofs)
1100 CASE "AVG"
1110   Navg=X(1)
1120   IF Navg<1 THEN Navg=1
1130   OUTPUT Sp;"OK AVG "&VAL$(Navg)
1140 CASE "AVGC"
1150   Navgc=X(1)
1160   IF Navgc<1 THEN Navgc=1
1170   OUTPUT Sp;"OK AVGC "&VAL$(Navgc)
1180 CASE "SETTLE"
1190   Settle=X(1)
1200   OUTPUT Sp;"OK SETTLE "&VAL$(Settle)
1210 CASE "MAXLVL"
1220   Maxlvl=X(1)
1230   OUTPUT Sp;"OK MAXLVL "&VAL$(Maxlvl)
1240 CASE "TARGET"
1250   Tgt=X(1)
1260   OUTPUT Sp;"OK TARGET "&VAL$(Tgt)
1270 CASE "WIN"
1280   Wa=X(1)
1290   IF Na>1 THEN Wb=X(2)
1300   OUTPUT Sp;"OK WIN "&VAL$(Wa)&" "&VAL$(Wb)
1310 CASE "FSTEP"
1320   Fstep=X(1)
1330   OUTPUT Sp;"OK FSTEP "&VAL$(Fstep)
1340 CASE "SSTEP"
1350   Sstep=X(1)
1360   OUTPUT Sp;"OK SSTEP "&VAL$(Sstep)
1361 CASE "TAIL"
1362   Tl=0
1363   IF A$="ON" OR A$="1" THEN Tl=1
1364   OUTPUT Sp;"OK TAIL "&VAL$(Tl)
1365 CASE "SCREEN"
1366   Scr=1
1367   IF A$="KEEP" THEN Scr=0
1368   OUTPUT Sp;"OK SCREEN "&VAL$(Scr)
1370 CASE "BRACKET"
1380   Brk=X(1)
1390   OUTPUT Sp;"OK BRACKET "&VAL$(Brk)
1391 CASE "UNCAP"
1392   ! the cap is the only guard between a sweep and full output, so this
1393   ! asks the generator what it can actually give on the port in use
1394   GOSUB Rf_lim
1395   IF Rhi>-900 THEN Maxlvl=Rhi
1396   DISP "Max level now ";PROUND(Maxlvl,-2);" dBm"
1397   OUTPUT Sp;"OK MAXLVL "&VAL$(PROUND(Maxlvl,-2))
1400 CASE "LEVEL"
1410   Lvl=X(1)
1420   IF Lvl>Maxlvl THEN Lvl=Maxlvl
1430   OUTPUT 800;"RFG:AMPL "&VAL$(Lvl)&" DBM"
1440   OUTPUT Sp;"OK LEVEL "&VAL$(Lvl)
1450 CASE "RF"
1460   IF A$="ON" THEN
1470     GOSUB Rf_on
1480   ELSE
1490     GOSUB Rf_off
1500   END IF
1510   OUTPUT Sp;"OK RF "&A$
1520 CASE "READ"
1530   N=Navg
1540   Pc$="R"
1550   GOSUB Meas
1560   OUTPUT Sp;"END"
1570 CASE "FIND"
1580   GOSUB Get_range
1590   Np=0
1600   GOSUB Rf_on
1610   GOSUB Find
1620   GOSUB Rf_off
1630   OUTPUT Sp;"END"
1640 CASE "FAST"
1650   GOSUB Get_range
1660   GOSUB Fast
1670 CASE "SWEEP"
1680   GOSUB Sweep
1690 CASE "STATUS"
1700   OUTPUT Sp;"OK FREQ "&VAL$(Freq)&" DEV "&VAL$(Dev)&" PL "&VAL$(Plf)
1710   OUTPUT Sp;"OK LEVEL "&VAL$(Lvl)&" OFFSET "&VAL$(Lofs)&" R12 "&VAL$(R12)
1720 E$="OK AFLVL "&VAL$(PROUND(Afv,-4))
1730 OUTPUT Sp;E$&" AFTGT "&VAL$(Aftgt)&" AFQ "&Afq$
1740 CASE "AFLVL"
1750   GOSUB Af_lvl
1760 CASE "TRIG"
1770   GOSUB Trig_set
1780 CASE "AFSC"
1790   GOSUB Af_sc
1800 CASE "RFLIM"
1810   GOSUB Rf_lim
1820 CASE "SCPI"
1830   GOSUB Scpi_do
1840 CASE "SCPIQ"
1850   GOSUB Scpi_qy
1860 CASE "AFTGT"
1870   GOSUB Af_tgt
1880 CASE "AFCMD"
1890   GOSUB Af_cmd
1900 CASE "AFPROBE"
1910   GOSUB Af_prb
1920 CASE "QUIT"
1930   GOTO Do_quit
1940 CASE ELSE
1950   OUTPUT Sp;"ERR UNKNOWN "&W$
1960 END SELECT
1970 RETURN
1980 !
1990 Split: Na=0 ! numbers in A$ -> X(1..3), count in Na
2000 X(1)=0
2010 X(2)=0
2020 X(3)=0
2030 B$=A$
2040 LOOP
2050   B$=TRIM$(B$)
2060 EXIT IF B$="" OR Na=3
2070   P=POS(B$," ")
2080   IF P=0 THEN P=LEN(B$)+1
2090   Na=Na+1
2100   ON ERROR GOTO Split_bad
2110   X(Na)=VAL(B$[1,P-1])
2120   OFF ERROR
2130 Split_next: IF P>LEN(B$) THEN
2140     B$=""
2150   ELSE
2160     B$=B$[P+1]
2170   END IF
2180 END LOOP
2190 RETURN
2200 Split_bad: OFF ERROR
2210 Na=Na-1
2220 GOTO Split_next
2230 !
2240 Get_range: Hi=Hstart
2250 Lo=Lstop
2260 IF Na>0 THEN Hi=X(1)
2270 IF Na>1 THEN Lo=X(2)
2280 Hstart=Hi
2290 Lstop=Lo
2300 RETURN
2310 !
2320 Init_ser: ! route serial input here. Manual p174 confirms SPOR9.
2321 GOSUB Dev_clr ! wipe the output queue; CLEAR is enough on its own
2340 OUTPUT 800;"*CLS"
2350 OUTPUT 800;"CONF:SPOR9:SIN 'IBASIC'"
2360 GOSUB Chk_err
2370 IF Errs>0 THEN
2380   PRINT "Could not set Serial In by command."
2390   PRINT "Set I/O CONFIGURE: Serial In = IBASIC."
2400 END IF
2410 RETURN
2420 !
2430 Set_keys: ON KEY 1 LABEL "SETUP" GOSUB K_setup
2440 ON KEY 2 LABEL "FIND12" GOSUB K_fast
2450 ON KEY 3 LABEL "FULLSWP" GOSUB K_sweep
2460 ON KEY 4 LABEL "RF OFF" GOSUB Rf_off
2470 ON KEY 5 LABEL "QUIT" GOTO Do_quit
2472 ! This instrument shows k1..k5 and no more - ON KEY 6 was tried and
2473 ! there is no sixth softkey for a standing UNCAP. The cap is raised
2474 ! by the UNCAP serial command, or from k1/k2 while Hl_ask is asking.
2480 RETURN
2490 K_setup: GOSUB Setup
2500 RETURN
2510 K_fast: Hi=Hstart
2520 Lo=Lstop
2530 GOSUB Fast
2540 RETURN
2550 K_sweep: Na=3
2560 X(1)=Hstart
2570 X(2)=Lstop
2580 X(3)=1
2590 GOSUB Sweep
2600 RETURN
2610 !
2620 Setup: IF Scr=1 THEN OUTPUT 800;"DISP RFG"
2625 OUTPUT 800;"CONF:RFD 'Freq'" ! p310: RFG:FREQ needs frequency tuning
2630 OUTPUT 800;"RFG:FREQ "&VAL$(Freq)&" MHZ"
2635 OUTPUT 800;"RFAN:FREQ "&VAL$(Freq)&" MHZ" ! keep the two together
2640 OUTPUT 800;"RFG:AMPL "&VAL$(Hstart)&" DBM"
2650 OUTPUT 800;"RFG:OUTP '"&Oport$&"'"
2660 OUTPUT 800;"AFG1:FREQ "&VAL$(Tone)&" HZ"
2670 OUTPUT 800;"AFG1:DEST 'FM'" ! p65: AFG1:FM needs this first
2680 OUTPUT 800;"AFG1:FM "&VAL$(Dev)&" KHZ"
2690 OUTPUT 800;"AFG1:FM:STAT ON"
2700 OUTPUT 800;"RFG:MOD:EXT:FM 0 KHZ" ! nothing from MODULATION IN
2710 GOSUB Set_pl
2720 IF Scr=1 THEN OUTPUT 800;"DISP AFAN"
2730 OUTPUT 800;"AFAN:INP 'Audio In'" ! manual p59, exact case
2740 OUTPUT 800;"MEAS:AFR:SEL 'SINAD'"
2750 GOSUB Chk_err
2760 IF Errs=0 THEN
2770   OUTPUT Sp;"OK SETUP"
2780 ELSE
2790   OUTPUT Sp;"ERR SETUP "&VAL$(Errs)&" INSTRUMENT ERRORS"
2800 END IF
2810 DISP "Setup done. Check filters/de-emphasis on AF ANL screen."
2820 RETURN
2830 !
2840 Set_pl: IF Plf>0 THEN
2850   OUTPUT 800;"AFG2:FREQ "&VAL$(Plf)&" HZ"
2860   OUTPUT 800;"AFG2:DEST 'FM'" ! p68: 'AM'|'FM'|'Audio Out'
2870   OUTPUT 800;"AFG2:FM "&VAL$(Pld)&" HZ"
2880   OUTPUT 800;"AFG2:FM:STAT ON"
2890 ELSE
2900   OUTPUT 800;"AFG2:DEST 'FM'" ! so a stale 'AM' cannot leave AM on
2910   OUTPUT 800;"AFG2:FM:STAT OFF"
2920 END IF
2930 RETURN
2940 !
2950 Rf_on: IF Lvl>Maxlvl THEN Lvl=Maxlvl
2960 OUTPUT 800;"RFG:AMPL "&VAL$(Lvl)&" DBM"
2970 OUTPUT 800;"RFG:AMPL:STAT ON"
2980 RETURN
2990 Rf_off: OUTPUT 800;"RFG:AMPL:STAT OFF"
3000 DISP "RF generator OFF"
3010 RETURN
3020 !
3030 ! Read the instrument error queue until it says it is empty.
3031 ! Two failure modes here used to corrupt every later reading, because
3032 ! both left a request on the bus whose answer was then returned as the
3033 ! NEXT query's result - a readback lagging by one query, which looks
3034 ! exactly like a screen full of wrong settings. Both now drain.
3035 Chk_err: Errs=0
3036 Er$=""
3037 Ecnt=0
3038 Ec_lp: E$=""
3039 ON TIMEOUT 8,2 GOTO Ec_to
3040 OUTPUT 800;"SYST:ERR?"
3041 ENTER 800;E$
3042 OFF TIMEOUT 8
3043 E2$=TRIM$(E$)
3044 IF E2$="" THEN RETURN ! nothing to say; treat as no error
3045 IF E2$[1,1]="+" OR E2$[1,1]="-" THEN E2$=TRIM$(E2$[2])
3046 IF E2$="" THEN RETURN
3047 IF POS("0123456789",E2$[1,1])=0 THEN GOTO Ec_bad
3048 IF E2$[1,1]="0" THEN RETURN ! +0,"No error" - the queue is empty
3049 Errs=Errs+1
3050 IF Er$="" THEN Er$=E$ ! keep the first, so a caller can attribute it
3051 IF Eq=0 THEN OUTPUT Sp;"WARN "&E$
3052 IF Eq=0 THEN PRINT "Instrument: ";E$
3053 Ecnt=Ecnt+1
3054 IF Ecnt<3 THEN GOTO Ec_lp
3055 RETURN
3056 !
3057 ! A reply that is not an error record at all means we are reading an
3058 ! answer meant for an earlier query. Report THAT, instead of passing the
3059 ! fragment off as an instrument error and asking again - which consumed
3060 ! another answer each time round and kept the queue permanently askew.
3061 Ec_bad: OUTPUT Sp;"WARN ERRQ OUT OF STEP: "&E$
3062 ! no PRINT here: the operator needs the 8935's own screen readable
3063 GOSUB Dev_clr
3064 OUTPUT 800;"*CLS"
3065 RETURN
3066 Ec_to: OFF TIMEOUT 8
3067 OUTPUT Sp;"WARN ERRQ TIMEOUT"
3068 GOSUB Dev_clr ! the unanswered SYST:ERR? would surface as the next answer
3069 OUTPUT 800;"*CLS"
3070 RETURN
3180 !
3190 Meas: IF Lvl>Maxlvl THEN Lvl=Maxlvl ! avg N reads -> S, spread -> Sd
3200 OUTPUT 800;"RFG:AMPL "&VAL$(Lvl)&" DBM"
3210 WAIT Settle
3220 FOR I=1 TO Ndisc
3230   IF Trg=1 THEN OUTPUT 800;"TRIG:IMM"
3240   OUTPUT 800;"MEAS:AFR:SINAD?"
3250   GOSUB Rd_800
3260 NEXT I
3270 Tot=0
3280 Tot2=0 ! sum of squares, for the per-point spread
3290 Ns=0
3300 FOR I=1 TO N
3310   IF Trg=1 THEN OUTPUT 800;"TRIG:IMM"
3320   OUTPUT 800;"MEAS:AFR:SINAD?"
3330   GOSUB Rd_800
3340   IF V<9.E+30 THEN
3350     Tot=Tot+V
3360     Tot2=Tot2+V*V
3370     Ns=Ns+1
3380   END IF
3390 NEXT I
3400 S=-999
3410 IF Ns>0 THEN S=Tot/Ns
3420 ! Sd = sample standard deviation of the N readings, -1 if N<2.
3430 ! Sd~0 across a whole run means the queries are not re-triggering.
3440 Sd=-1
3450 IF Ns>1 THEN
3460   Vr=(Tot2-Tot*Tot/Ns)/(Ns-1)
3470   IF Vr<0 THEN Vr=0 ! rounding can make it slightly negative
3480   Sd=SQR(Vr)
3490 END IF
3500 IF Np<300 THEN
3510   Np=Np+1
3520   Lv(Np)=Lvl
3530   Sn(Np)=S
3540   Ph$(Np)=Pc$
3550 END IF
3560 E$="PT,"&Pc$&","&VAL$(PROUND(Lvl,-2))&","&VAL$(PROUND(S,-2))
3570 OUTPUT Sp;E$&","&VAL$(Ns)&","&VAL$(PROUND(Sd,-3))
3571 ! Built with padding rather than PRINT with ";" separators, which sizes
3572 ! each number to its own digits so the columns walk about as the level
3573 ! goes from -60 to -135 and SINAD from 40 to 2.
3574 Ln$=Pc$&" "
3575 Nb$=VAL$(PROUND(Lvl+Lofs,-2))
3576 Nw=8
3577 GOSUB Pad
3578 Ln$=Ln$&Nb$&" dBm  SINAD "
3579 Nb$=VAL$(PROUND(S,-1))
3581 Nw=5
3582 GOSUB Pad
3583 Ln$=Ln$&Nb$&" dB"
3584 IF Sd>=0 THEN
3585   Nb$=VAL$(PROUND(Sd,-1))
3586   Nw=5
3587   GOSUB Pad
3588   Ln$=Ln$&"  sd"&Nb$
3589 END IF
3591 PRINT Ln$
3592 DISP Ln$
3593 RETURN
3600 !
3610 Find: N=Navgc ! bracket Tgt between Hi and Lo
3620 Ok=0
3630 Pc$="C"
3635 ! Climb if the start level does not clear the target. A desensed
3636 ! receiver, or a lossy path, simply needs more drive than --start, and
3637 ! failing there wasted the run. 20 dB a step, stopping at Maxlvl, which
3638 ! is the only thing between this and the generator's full output.
3640 Lvl=Hi
3650 GOSUB Meas
3654 Climb: WHILE S<Tgt+3 AND Hi<Maxlvl-.001
3656   Hi=Hi+20
3657   IF Hi>Maxlvl THEN Hi=Maxlvl
3658   OUTPUT Sp;"WARN RAISING START TO "&VAL$(PROUND(Hi,-2))&" DBM"
3659   Lvl=Hi
3661   GOSUB Meas
3662 END WHILE
3663 IF S<Tgt+3 THEN
3664   ! the level and the SINAD reached, so the laptop can offer the
3665   ! generator's real ceiling rather than only reporting a failure
3666   OUTPUT Sp;"ERR HIGHLVL,"&VAL$(PROUND(Hi,-2))&","&VAL$(PROUND(S,-2))
3667   GOSUB Hl_ask
3668   IF Maxlvl>Hi+.001 THEN GOTO Climb
3680   RETURN
3690 END IF
3700 Lvl=Lo
3710 GOSUB Meas
3720 IF S>Tgt THEN
3730   OUTPUT Sp;"ERR SINAD AT LOW LEVEL STILL ABOVE TARGET"
3740   RETURN
3750 END IF
3760 Pc$="B"
3770 WHILE Hi-Lo>Brk
3780   Lvl=(Hi+Lo)/2
3790   GOSUB Meas
3800   IF S>=Tgt THEN
3810     Hi=Lvl
3820   ELSE
3830     Lo=Lvl
3840   END IF
3850 END WHILE
3860 Est=(Hi+Lo)/2
3870 Ok=1
3880 OUTPUT Sp;"BRACKET,"&VAL$(PROUND(Lo,-2))&","&VAL$(PROUND(Hi,-2))
3890 RETURN
3900 !
3905 PRINT
3906 PRINT "FAST ";PROUND(Freq,-4);" MHz  offset ";PROUND(Lofs,-2);" dB"
3910 Fast: Np=0 ! bisection, sparse points, fine sweep, fit
3920 Hs=Hi
3925 Ls=Lo ! Find moves Lo as it bisects; keep the level that was asked for
3930 GOSUB Rf_on
3940 GOSUB Find
3950 IF Ok=0 THEN GOTO Fast_end
3960 Top=Est+Wa
3970 IF Sstep>0 THEN
3980   N=Navgc
3990   Pc$="S"
4000   L0=Hs
4010   WHILE L0>Top+1
4020     Lvl=L0
4030     GOSUB Meas
4040     L0=L0-Sstep
4050   END WHILE
4060 END IF
4070 N=Navg
4080 Pc$="F"
4090 L0=Top
4100 WHILE L0>=Est-Wb-.001
4110   Lvl=L0
4120   GOSUB Meas
4130   L0=L0-Fstep
4140 END WHILE
4141 ! Coarse points below the fine window as well as above it. Without these
4142 ! the curve stops at the bottom of the fit window, a few dB under the
4143 ! target, and never shows where it flattens into the noise floor - which
4144 ! is the part that says whether the measurement bottomed out or the
4145 ! receiver did. Same step and same averaging as the sparse points above.
4146 IF Sstep>0 AND Tl=1 THEN
4147   N=Navgc
4148   Pc$="S"
4149   L0=Est-Wb-Sstep
4150   WHILE L0>=Ls-.001
4151     Lvl=L0
4152     GOSUB Meas
4153     L0=L0-Sstep
4154   END WHILE
4155 END IF
4156 GOSUB Fit
4160 Fast_end: GOSUB Rf_off
4170 OUTPUT Sp;"END"
4180 RETURN
4190 !
4200 Sweep: Np=0 ! linear sweep X(1) to X(2) in X(3) steps
4210 IF Na<3 THEN X(3)=1
4220 IF Na<2 THEN X(2)=Lstop
4230 IF Na<1 THEN X(1)=Hstart
4240 N=Navg
4250 Pc$="L"
4260 Lvl=X(1)
4270 GOSUB Rf_on
4280 Below=0
4290 L0=X(1)
4300 WHILE L0>=X(2)-.001
4310   Lvl=L0
4320   GOSUB Meas
4330   IF S<3 THEN
4340     Below=Below+1
4350   ELSE
4360     Below=0
4370   END IF
4380   L0=L0-ABS(X(3))
4390   IF Below>=3 THEN L0=-999
4400 END WHILE
4410 GOSUB Fit
4420 GOSUB Rf_off
4430 OUTPUT Sp;"END"
4440 RETURN
4450 !
4460 Fit: R12=-999 ! least squares line near Tgt
4470 Nf=0
4480 Sx=0
4490 Sy=0
4500 Sxx=0
4510 Sxy=0
4520 FOR I=1 TO Np
4530   IF Ph$(I)<>"B" AND Ph$(I)<>"C" THEN
4540     IF Sn(I)>=Tgt-5 AND Sn(I)<=Tgt+7 THEN
4550       Nf=Nf+1
4560       Sx=Sx+Lv(I)
4570       Sy=Sy+Sn(I)
4580       Sxx=Sxx+Lv(I)*Lv(I)
4590       Sxy=Sxy+Lv(I)*Sn(I)
4600     END IF
4610   END IF
4620 NEXT I
4630 IF Nf<3 THEN
4640   OUTPUT Sp;"WARN FIT NEEDS 3 POINTS NEAR TARGET, HAVE "&VAL$(Nf)
4650   RETURN
4660 END IF
4670 Den=Nf*Sxx-Sx*Sx
4680 IF Den=0 THEN RETURN
4690 Sl=(Nf*Sxy-Sx*Sy)/Den
4700 Ic=(Sy-Sl*Sx)/Nf
4710 IF Sl<=.2 THEN
4720   OUTPUT Sp;"WARN FIT SLOPE TOO SMALL"
4730   RETURN
4740 END IF
4750 R12=(Tgt-Ic)/Sl
4760 Uv=SQR(10^((R12+Lofs)/10)*.05)*1.E+6
4770 E$="RESULT,"&VAL$(PROUND(R12,-2))&","&VAL$(PROUND(R12+Lofs,-2))
4780 OUTPUT Sp;E$&","&VAL$(PROUND(Uv,-3))
4785 PRINT Tgt;"dB SINAD at";PROUND(R12+Lofs,-2);"dBm ";PROUND(Uv,-3);"uV"
4790 DISP Tgt;"dB SINAD at";PROUND(R12+Lofs,-2);"dBm";PROUND(Uv,-3);"uV"
4800 RETURN
4810 !
4820 Do_quit: OUTPUT 800;"RFG:AMPL:STAT OFF"
4830 OUTPUT Sp;"OK BYE"
4840 OUTPUT 800;"CONF:SPOR9:SIN 'Inst'" ! manual p174, exact case
4850 GOSUB Chk_err
4860 DISP "SINADCTL stopped. Serial In returned to Inst."
4870 STOP ! END must be the last line; GOSUB targets may not follow it
4880 !
4890 ! ---- AF level / volume-set support -------------------------------
4900 !
4910 Af_lvl: N=Navg ! average N AC Level readings -> Afv
4920 IF Na>0 THEN N=X(1)
4930 IF N<1 THEN N=1
4940 Tot=0
4950 Tot2=0
4960 Ns=0
4970 FOR I=1 TO N
4980   IF Trg=1 THEN OUTPUT 800;"TRIG:IMM" ! force a fresh acquisition
4990   OUTPUT 800;Afq$
5000   GOSUB Rd_800
5010   IF V<9.E+30 THEN
5020     Tot=Tot+V*Afsc
5030     Tot2=Tot2+V*Afsc*V*Afsc
5040     Ns=Ns+1
5050   END IF
5060 NEXT I
5070 Afv=-1
5080 IF Ns>0 THEN Afv=Tot/Ns
5090 Sd=-1
5100 IF Ns>1 THEN
5110   Vr=(Tot2-Tot*Tot/Ns)/(Ns-1)
5120   IF Vr<0 THEN Vr=0
5130   Sd=SQR(Vr)
5140 END IF
5150 E$="AFL,"&VAL$(PROUND(Afv,-4))&","&VAL$(Ns)
5160 OUTPUT Sp;E$&",ACL,"&VAL$(PROUND(Sd,-4))
5170 DISP "AF ";PROUND(Afv,-3);" V  target ";Aftgt;"+/-";Aftol
5180 RETURN
5190 !
5200 Af_tgt: IF Na>0 THEN Aftgt=X(1)
5210 IF Na>1 THEN Aftol=X(2)
5220 OUTPUT Sp;"OK AFTGT "&VAL$(Aftgt)&" "&VAL$(Aftol)
5230 RETURN
5240 !
5250 Af_cmd: IF Qa$<>"" THEN Afq$=Qa$ ! bare AFCMD just reports it
5260 OUTPUT Sp;"OK AFCMD "&Afq$
5270 RETURN
5280 !
5290 ! AFPROBE reads the AC Level plus its units, so checklist 1.5 is answered
5300 ! by query rather than by reading the screen.
5310 Af_prb: OUTPUT 800;"*CLS"
5320 V=-1.E+3
5330 OUTPUT 800;Afq$
5340 GOSUB Rd_800
5350 GOSUB Chk_err
5360 IF Errs=0 AND V<9.E+30 THEN
5370   OUTPUT Sp;"AFP,"&Afq$&","&VAL$(PROUND(V,-4))&",OK"
5380 ELSE
5390   OUTPUT Sp;"AFP,"&Afq$&",,ERR"
5400 END IF
5410 OUTPUT 800;"MEAS:AFR:ACL:UNits?"
5420 GOSUB Rds800
5430 Tg$=Sq$
5440 GOSUB Chk_err
5450 IF Errs=0 AND Tg$<>"" THEN
5460   OUTPUT Sp;"AFP,UNITS,"&Tg$&",OK"
5470 ELSE
5480   OUTPUT Sp;"AFP,UNITS,,ERR"
5490 END IF
5500 OUTPUT Sp;"END"
5510 RETURN
5520 !
5530 ! Manual p346: TRIG:IMM triggers all selected measurements, and
5540 ! TRIG:MODE:RETR SINGle stops free-running. With TRIG ON every read is a
5550 ! fresh acquisition by construction instead of whatever the display held.
5560 Trig_set: IF A$="ON" THEN
5570   Trg=1
5580   OUTPUT 800;"TRIG:MODE:RETR SING"
5590 ELSE
5600   Trg=0
5610   OUTPUT 800;"TRIG:MODE:RETR REP"
5620 END IF
5630 GOSUB Chk_err
5640 OUTPUT Sp;"OK TRIG "&A$&" ERRS "&VAL$(Errs)
5650 RETURN
5660 !
5670 ! AFSC scales the raw reading to volts, for the case where MEAS:AFR:ACL?
5680 ! answers in something other than V. AFPROBE reports the units.
5690 Af_sc: IF Na>0 THEN Afsc=X(1)
5700 IF Afsc=0 THEN Afsc=1
5710 OUTPUT Sp;"OK AFSC "&VAL$(Afsc)
5720 RETURN
5730 !
5740 ! RFLIM asks the generator for its own output range. The GPIB syntax
5750 ! reference documents RFG:AMPL but not its limits, so the instrument is
5760 ! the only authority. Two behaviours are possible and both are handled:
5770 ! a set that is out of range may be CLAMPED (the readback comes back
5780 ! lower than asked) or REJECTED (an error, value unchanged). The limits
5790 ! depend on the output port, so the port in force is reported with them.
5800 Rf_lim: Sav=Lvl
5810 Rhi=-999
5820 Rlo=-999
5825 ! Every rejected level here is the measurement, not a fault: the probe
5826 ! asks for levels it expects to be refused and reads which ones stick.
5827 ! Reporting each one sent a dozen -200 warnings up the serial line.
5828 Eq=1
5830 OUTPUT 800;"*CLS"
5840 OUTPUT 800;"RFG:AMPL 30 DBM"
5850 GOSUB Chk_err
5860 Er1=Errs
5870 OUTPUT 800;"RFG:AMPL?"
5880 GOSUB Rd_800
5890 Rhi=V
5900 IF Er1>0 OR ABS(Rhi-30)<.05 THEN
5910   ! rejected, or it really accepted +30: bisect for the true ceiling
5920   Bh=30
5930   Bl=-60
5940   WHILE Bh-Bl>.1
5950     Bm=(Bh+Bl)/2
5960     OUTPUT 800;"*CLS"
5970     OUTPUT 800;"RFG:AMPL "&VAL$(Bm)&" DBM"
5980     GOSUB Chk_err
5990     OUTPUT 800;"RFG:AMPL?"
6000     GOSUB Rd_800
6010     Rb=V
6020     IF Errs=0 AND ABS(Rb-Bm)<.05 THEN
6030       Bl=Bm
6040     ELSE
6050       Bh=Bm
6060     END IF
6070   END WHILE
6080   Rhi=Bl
6090 END IF
6100 OUTPUT 800;"*CLS"
6110 OUTPUT 800;"RFG:AMPL -200 DBM"
6120 GOSUB Chk_err
6130 OUTPUT 800;"RFG:AMPL?"
6140 GOSUB Rd_800
6150 Rlo=V
6155 Eq=0
6160 OUTPUT 800;"RFG:AMPL "&VAL$(Sav)&" DBM"
6170 E$="RFLIM,"&VAL$(PROUND(Rlo,-2))&","&VAL$(PROUND(Rhi,-2))
6180 OUTPUT Sp;E$&","&Oport$
6190 OUTPUT Sp;"END"
6200 DISP "RF generator range ";PROUND(Rlo,-1);" to ";PROUND(Rhi,-1);" dBm"
6210 RETURN
6220 !
6230 ! SCPI / SCPIQ forward one command or query to the instrument bus. One
6240 ! generic pair costs far less program space than a command per setting,
6250 ! and lets the laptop configure and read back anything - the audio filter
6260 ! chain, de-emphasis, detector - without another reload. The argument is
6270 ! taken from Qa$ so its case survives: 'C MESSAGE' is not 'c message'.
6280 Scpi_do: IF Qa$="" THEN
6290   OUTPUT Sp;"ERR SCPI NEEDS A COMMAND"
6300   RETURN
6310 END IF
6320 OUTPUT 800;"*CLS"
6330 OUTPUT 800;Qa$
6340 GOSUB Chk_err
6350 OUTPUT Sp;"OK SCPI "&VAL$(Errs)
6351 IF Errs>0 THEN OUTPUT Sp;"SCPIE,"&Qa$&","&Er$
6360 RETURN
6370 !
6380 Scpi_qy: IF Qa$="" THEN
6390   OUTPUT Sp;"ERR SCPIQ NEEDS A QUERY"
6400   RETURN
6410 END IF
6411 ! *CLS clears the error queue but NOT the output queue (IEEE 488.2:
6412 ! that needs a device clear), so a response orphaned by an earlier
6413 ! timeout survives it and comes back as this query's answer. Draining
6414 ! here first was worse than the disease: reading an empty bus provokes
6415 ! a -420 query error on every single query. The echo on the reply
6416 ! makes a slipped answer visible instead, and reading it puts the
6417 ! queue back in step, so the laptop just asks again.
6420 OUTPUT 800;"*CLS"
6430 Sq$=""
6440 ON TIMEOUT 8,3 GOTO Scpi_to
6450 OUTPUT 800;Qa$
6460 ENTER 800;Sq$
6461 OFF TIMEOUT 8
6462 GOTO Scpi_ok
6470 Scpi_to: OFF TIMEOUT 8
6471 Sq$=""
6472 GOSUB Dev_clr ! a late answer would otherwise become the next reply
6473 OUTPUT 800;"*CLS"
6480 Scpi_ok: GOSUB Chk_err
6481 ! The reply carries the query back with it. Without that echo a reply
6482 ! that has slipped by one is indistinguishable from the right answer,
6483 ! and the laptop reports a whole screenful of plausible wrong state.
6490 OUTPUT Sp;"SCPIQ,"&Qa$&","&Sq$
6491 IF Errs>0 THEN OUTPUT Sp;"SCPIE,"&Qa$&","&Er$
6500 RETURN
6510 !
6520 !
6530 ! Every read from the instrument bus goes through these. Without a
6540 ! timeout, a query that is not answered blocks the program for ever: the
6550 ! laptop sees silence, the 8935 reports an HP-IB query error, and the
6560 ! only way out is stopping the program at the front panel. That is
6570 ! exactly what happened on the first hardware run. The sentinel is a
6580 ! value every caller already treats as 'no reading', so a timeout costs
6590 ! one sample instead of the session.
6600 Rd_800: V=9.91E+37
6610 ON TIMEOUT 8,5 GOTO Rd_to
6620 ENTER 800;V
6630 Rd_to: OFF TIMEOUT 8
6640 RETURN
6650 !
6660 Rds800: Sq$=""
6670 ON TIMEOUT 8,5 GOTO Rds_to
6680 ENTER 800;Sq$
6690 Rds_to: OFF TIMEOUT 8
6700 RETURN
6710 !
6720 ! There was a Flush routine here that drained the output queue by
6730 ! reading it until a read came back empty. Reading an idle bus provokes
6740 ! "-420 Query UNTERMINATED", which the 8935 puts on its screen, so it
6750 ! announced itself every time it ran. Dev_clr does the same job
6751 ! properly with a device clear and provokes nothing, so Flush is gone
6752 ! and every caller goes there instead.
6831 !
6832 ! *CLS cannot touch the output queue; IEEE 488.2 gives that job to a
6833 ! device clear, which is what HP BASIC's CLEAR sends. The bench queue
6834 ! held a BACKLOG of chopped fragments - a raw SCPIQ drained "+" and
6835 ! "0" as separate items - which *CLS, QUIT and reloading all kept.
6836 ! Verified on this unit: the first state read after it came back clean
6837 ! where every earlier one was fragments. ON ERROR kept as it is free.
6838 Dev_clr: ON ERROR GOTO Dv_no
6839 CLEAR 800
6841 Dv_no: OFF ERROR
6842 RETURN
6843 !
6844 ! PRINT goes wherever PRINTER IS points, set on the PRINTER CONFIGURE
6845 ! screen. Left alone a run's history could go to a real printer - or, far
6846 ! worse, to serial 9, the link this program is driven over. Pin it here.
6847 Set_prt: ON ERROR GOTO Sp_no
6848 PRINTER IS CRT
6849 Sp_no: OFF ERROR
6851 RETURN
6852 !
6853 ! Right-justify Nb$ into Nw. Padding is one subroutine; a PRINT USING
6854 ! image is one more piece of syntax to be wrong about on hardware.
6855 Pad: Bl$="            "
6856 IF LEN(Nb$)<Nw THEN Nb$=Bl$[1,Nw-LEN(Nb$)]&Nb$
6857 RETURN
6858 !
6859 ! Ask at the instrument, but only here - the moment the climb runs out
6860 ! of cap. ON KEY is the only front-panel input IBASIC gets on this box:
6861 ! KBD$ compiled and ran, and the keypad's "1" went to the front panel,
6862 ! which answered "Invalid keystroke" (measured 2026-10-08). So k1/k2 are
6863 ! borrowed for the few seconds of the prompt and Set_keys puts them back;
6864 ! leaving them borrowed would cost the operator SETUP and FIND12 all day.
6865 ! Rf_lim is called after the wait, not inside the key branch, to keep the
6866 ! interrupt handler one statement deep.
6867 Hl_ask: Uk=0
6868 ON KEY 1 LABEL "UNCAP" GOSUB Hl_yes
6869 ON KEY 2 LABEL "STOP" GOSUB Hl_no
6870 DISP "No "&VAL$(Tgt)&"dB at "&VAL$(PROUND(Hi,-2))&"dBm: k1=UNCAP k2=stop"
6871 Kt=0
6872 LOOP
6873   IF Uk>0 THEN GOTO Hl_d
6874   Kt=Kt+1
6875   IF Kt>150 THEN GOTO Hl_d
6876   WAIT .1
6877 END LOOP
6878 Hl_d: GOSUB Set_keys
6879 IF Uk=1 THEN
6880   GOSUB Rf_lim
6881   IF Rhi>-900 THEN Maxlvl=Rhi
6882   ! Raising the cap to a ceiling the climb has already reached changes
6883   ! nothing, and saying "UNCAPPED" there would be a lie. Say which it is.
6884   IF Maxlvl>Hi+.001 THEN
6885     OUTPUT Sp;"WARN UNCAPPED TO "&VAL$(PROUND(Maxlvl,-2))&" DBM"
6886   ELSE
6887     OUTPUT Sp;"WARN NO HEADROOM, CEILING "&VAL$(PROUND(Maxlvl,-2))&" DBM"
6888     DISP "Generator at its ceiling, "&VAL$(PROUND(Maxlvl,-2))&" dBm"
6889   END IF
6890 END IF
6891 RETURN
6892 Hl_yes: Uk=1
6893 RETURN
6894 Hl_no: Uk=2
6895 RETURN
6900 END
