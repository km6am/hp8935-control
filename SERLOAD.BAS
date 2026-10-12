10 ! SERLOAD - receive an ASCII program on serial port 9 into a RAM file
20 DIM In$[200],F$[20],M$[20]
30 F$="SNDTMP"
40 M$=":MEMORY,0,0"
50 MSI M$
60 ON ERROR GOTO Purged
70 PURGE F$
80 Purged: OFF ERROR
85 ! load.py rewrites this record count as it types the loader, sizing the
86 ! file to the program being sent. The number here is only the fallback
87 ! for typing SERLOAD by hand. Too small fails at line 210 with ERROR 59
88 ! a minute into the stream; too big fails here with ERROR 64.
90 CREATE ASCII F$,96
100 ASSIGN @F TO F$
110 OUTPUT 800;"CONF:SPOR9:SIN 'IBASIC'"
120 PRINT "SERLOAD: waiting for program on serial 9"
130 OUTPUT 9;"LOADER READY"
140 First: ON TIMEOUT 9,2 GOTO First
150 ENTER 9;In$
160 OUTPUT @F;In$
165 OUTPUT 9;"LOADER FIRST "&In$
170 Nl=1
180 LOOP
190   ON TIMEOUT 9,5 GOTO Done
200   ENTER 9;In$
210   OUTPUT @F;In$
220   Nl=Nl+1
230   DISP "Lines received: ";Nl
240 END LOOP
250 Done: OFF TIMEOUT 9
260 ASSIGN @F TO *
270 OUTPUT 800;"CONF:SPOR9:SIN 'Inst'"
280 OUTPUT 9;"LOADER DONE "&VAL$(Nl)
290 PRINT "SERLOAD: ";Nl;" lines saved to ";F$;M$
300 PRINT "Now: GET ";CHR$(34);F$;CHR$(34);" then RUN"
310 END
