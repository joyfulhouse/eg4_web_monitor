# Shared Register Map Analysis (0x404-0x2936)
# Region size: 9523 bytes (0x2533)

## Raw Hex Dump (first 512 bytes)
```
  0404: 9a 00 00 06 02 1a 76 1f 03 b8 07 34 8a a9 8f 40   ......v....4...@
  0414: ff ff a0 c4 ff 20 01 44 07 34 8a a9 cc c4 ff f8   ..... .D.4......
  0424: 50 05 88 a9 ff 20 01 44 07 34 8a a9 b6 00 ff 20   P.... .D.4.....
  0434: 01 52 7e c4 07 34 8a a9 ff 20 01 44 c3 c4 07 34   .R~..4... .D...4
  0444: 8a a9 cc c4 ff f8 50 02 88 a9 ff 20 01 44 07 34   ......P.... .D.4
  0454: 8a a9 7e c4 ff 20 01 44 07 34 8a a9 cc c4 ff f8   ..~.. .D.4......
  0464: 50 05 88 a9 ff 20 01 44 07 34 8a a9 ff 20 01 60   P.... .D.4... .`
  0474: 7e c4 07 34 8a a9 ff 20 01 44 c3 c4 07 34 8a a9   ~..4... .D...4..
  0484: cc c4 ff f8 50 02 88 a9 ff 20 01 44 07 34 8a a9   ....P.... .D.4..
  0494: 7e c4 ff 20 01 44 07 34 8a a9 cc c4 ff f8 50 05   ~.. .D.4......P.
  04a4: 88 a9 ff 20 01 44 07 34 8a a9 ff 20 01 62 7e c4   ... .D.4... .b~.
  04b4: 07 34 8a a9 ff 20 01 44 c3 c4 07 34 8a a9 cc c4   .4... .D...4....
  04c4: ff f8 50 02 88 a9 ff 20 01 44 07 34 8a a9 7e c4   ..P.... .D.4..~.
  04d4: 9a 00 00 06 02 1a 76 1f 03 b8 07 34 8a a9 8f 40   ......v....4...@
  04e4: ff ff a0 c4 ff 20 01 44 07 34 8a a9 cc c4 ff f8   ..... .D.4......
  04f4: 50 05 88 a9 ff 20 01 44 07 34 8a a9 b6 00 ff 20   P.... .D.4.....
  0504: 01 52 7e c4 07 34 8a a9 ff 20 01 44 c3 c4 07 34   .R~..4... .D...4
  0514: 8a a9 cc c4 ff f8 50 02 88 a9 ff 20 01 44 07 34   ......P.... .D.4
  0524: 8a a9 7e c4 9a 00 00 06 fe 02 76 22 76 1f 01 c0   ..~.......v"v...
  0534: 92 29 90 07 96 41 92 41 50 68 96 29 76 1a ff 69   .)...A.APh.)v..i
  0544: fe 82 00 06 fe 04 76 22 02 00 76 1f 01 f0 1e 3c   ......v"..v....<
  0554: 76 1f 01 f1 1e 3c 76 1f 01 f2 1e 3c 76 1f 01 f3   v....<v....<v...
  0564: 1e 3c 76 1f 01 f4 1e 3c 76 1f 01 f5 1e 3c 8f 00   .<v....<v....<..
  0574: 7c 00 a8 42 2b 43 92 43 52 c0 67 0f 29 01 be 00   |..B+C.CR.g.)...
  0584: 90 1f 52 06 61 06 56 03 01 43 07 42 8a a9 c2 c4   ..R.a.V..C.B....
  0594: 0a 43 92 43 52 c0 68 f5 8f 00 7f 00 a8 42 2b 43   .C.CR.h......B+C
  05a4: 92 43 52 18 67 0c 29 01 be 00 56 03 01 43 07 42   .CR.g.)...V..C.B
  05b4: 8a a9 c2 c4 0a 43 92 43 52 18 68 f8 76 1a fe 84   .....C.CR.h.v...
  05c4: ff 69 00 06 76 22 76 1f 17 48 cc 08 ff fc 50 02   .i..v"v..H....P.
  05d4: 96 08 76 1a ff 69 00 06 76 22 76 1f 17 48 18 08   ..v..i..v"v..H..
  05e4: ff f7 18 08 ff fc 76 1a ff 69 00 06 76 22 76 1f   ......v..i..v"v.
  05f4: 17 48 18 08 ff ef cc 08 ff fc 50 01 96 08 76 1a   .H........P...v.
```

## Structure Pattern Analysis

Total 16-bit words: 4761

### Most common 16-bit words
| Value (hex) | Value (dec) | Count | Notes |
|-------------|-------------|-------|-------|
| 0x0001 |     1 |    61 | Scale factor? (1/1) |
| 0x0000 |     0 |    59 | Zero |
| 0x1F76 |  8054 |    52 |  |
| 0x0100 |   256 |    37 |  |
| 0xD092 | 53394 |    36 |  |
| 0x00C0 |   192 |    34 |  |
| 0x0040 |    64 |    34 |  |
| 0x0080 |   128 |    34 |  |
| 0xA98A | 43402 |    33 |  |
| 0x00C1 |   193 |    33 |  |
| 0x0081 |   129 |    32 |  |
| 0x0041 |    65 |    32 |  |
| 0x4076 | 16502 |    31 |  |
| 0x008D |   141 |    31 |  |
| 0x9292 | 37522 |    30 |  |
| 0x0600 |  1536 |    28 |  |
| 0xBF56 | 48982 |    25 |  |
| 0x922B | 37419 |    25 |  |
| 0xA9A8 | 43432 |    25 |  |
| 0x20FF |  8447 |    24 |  |
| 0x0002 |     2 |    23 |  |
| 0x3407 | 13319 |    22 |  |
| 0x541E | 21534 |    22 |  |
| 0x9296 | 37526 |    22 |  |
| 0xB803 | 47107 |    21 |  |
| 0xFF00 | 65280 |    21 |  |
| 0xA60F | 42511 |    21 |  |
| 0x4401 | 17409 |    20 |  |
| 0x0356 |   854 |    20 |  |
| 0x348A | 13450 |    20 |  |

### Marker Pattern Search


## Structured Record Decoding Attempts

### Sequential Value Search (potential register numbers)

No sequential incrementing runs found (register numbers may not be stored linearly)

### Known Value Search

  Value 48 (48V (battery nominal voltage)): found at word positions 606, 608, 610, 612

### C28x Instruction Analysis of Register Region

This region may contain C28x code that implements register handling.
Common C28x opcodes in this region:

  0x88A9:    1 occurrences - possible data / immediate value
  0xB600:    1 occurrences - MOVH *+XAR6[0],ACC

### Hypothesis: This region is C28x DSP code, not a raw data table

The high frequency of values like 0x8AA9, 0xFF20, 0x0734, 0xCCC4 suggests
this is compiled C28x code (register load/store operations), not a flat
table of register definitions. The register map is likely encoded as code
that initializes register default values, validates ranges, and applies
scaling factors programmatically.

### Embedded Constants Analysis

Found 0 immediate values from MOV/load patterns
Most common immediate values:
| Value (hex) | Value (dec) | Count | Possible Meaning |
|-------------|-------------|-------|------------------|

## Raw Hex Dump (last 256 bytes of region)
```
  2837: bc 00 7c 00 b4 00 74 00 75 00 b5 00 77 00 b7 00   ..|...t.u...w...
  2847: b6 00 76 00 72 00 b2 00 b3 00 73 00 b1 00 71 00   ..v.r.....s...q.
  2857: 70 00 b0 00 50 00 90 00 91 00 51 00 93 00 53 00   p...P.....Q...S.
  2867: 52 00 92 00 96 00 56 00 57 00 97 00 55 00 95 00   R.....V.W...U...
  2877: 94 00 54 00 9c 00 5c 00 5d 00 9d 00 5f 00 9f 00   ..T...\.]..._...
  2887: 9e 00 5e 00 5a 00 9a 00 9b 00 5b 00 99 00 59 00   ..^.Z.....[...Y.
  2897: 58 00 98 00 88 00 48 00 49 00 89 00 4b 00 8b 00   X.....H.I...K...
  28a7: 8a 00 4a 00 4e 00 8e 00 8f 00 4f 00 8d 00 4d 00   ..J.N.....O...M.
  28b7: 4c 00 8c 00 44 00 84 00 85 00 45 00 87 00 47 00   L...D.....E...G.
  28c7: 46 00 86 00 82 00 42 00 43 00 83 00 41 00 81 00   F.....B.C...A...
  28d7: 80 00 40 fe 04 8f 0b ff 00 92 c4 96 43 8f 08 20   ..@.........C..
  28e7: 00 92 c4 96 42 92 43 52 aa ed 06 92 42 52 aa ed   ....B.CR....BR..
  28f7: 03 00 48 21 00 00 48 14 7f fe 04 a0 44 a8 42 06   ..H!..H.....D.B.
  2907: 44 0f 42 69 0c 8a 42 92 84 a8 42 8a 48 c4 a4 de   D.Bi..B...B.H...
  2917: 01 c2 48 96 c4 06 44 0f 42 66 f6 fe 84 00 06 56   ..H...D.Bf.....V
  2927: 1f 76 22 b9 c0 28 29 00 68 76 1a 00 48 00 10 ff   .v"..().hv..H...
```
