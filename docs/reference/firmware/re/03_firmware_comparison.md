# Firmware Comparison: 18kPV vs FlexBOSS21

18kPV size:       286,221 bytes
FlexBOSS size:    284,543 bytes
Size delta:        +1,678 bytes

Total byte differences: 250163

## Differences by Region
| Region | Offset Range | Diff Count |
|--------|-------------|------------|
| Header (0x000-0x005) | 0x0000-0x0005 | 0 |
| FF Padding (0x006-0x020) | 0x0006-0x0020 | 0 |
| Config Metadata (0x021-0x03D) | 0x0021-0x003D | 0 |
| FF Padding (0x03E-0x403) | 0x003E-0x0403 | 2 |
| Shared Register Region (0x404-0x2936) | 0x0404-0x2936 | 30 |
| Gap (0x2937-0x3230) | 0x2937-0x3230 | 8 |
| DSP Code (0x3231+) | 0x3231-0x45E0C | 250123 |

## Register Region Differences (detailed)

- Block checksum differences: 24
- Actual data differences: 6

### Data Differences (non-checksum)
| Offset | Block | PosInBlock | 18kPV | FlexBOSS | Notes |
|--------|-------|------------|-------|----------|-------|
| 0x101A | 5 | 267 | 0x61 | 0x41 | Case diff: 'a' vs 'A' |
| 0x101E | 5 | 271 | 0x65 | 0x45 | Case diff: 'e' vs 'E' |
| 0x101F | 5 | 272 | 0x61 | 0x41 | Case diff: 'a' vs 'A' |
| 0x1027 | 5 | 280 | 0x61 | 0x41 | Case diff: 'a' vs 'A' |
| 0x102A | 5 | 283 | 0x61 | 0x41 | Case diff: 'a' vs 'A' |
| 0x102B | 5 | 284 | 0x65 | 0x45 | Case diff: 'e' vs 'E' |

## DSP Code Region Differences
Total byte differences in DSP region: 250123

Grouped into 11202 contiguous difference regions

### Difference Regions (first 40)
| # | Start | End | Size | Notes |
|---|-------|-----|------|-------|
|   0 | 0x03247 | 0x03248 |    2 | BE: 6982 vs 6486, LE: 17947 vs 22041 |
|   1 | 0x0326F | 0x03270 |    2 | BE: 6982 vs 6486, LE: 17947 vs 22041 |
|   2 | 0x03293 | 0x03294 |    2 | BE: 6982 vs 6486, LE: 17947 vs 22041 |
|   3 | 0x032B9 | 0x032BA |    2 | BE: 6982 vs 6486, LE: 17947 vs 22041 |
|   4 | 0x03331 | 0x03332 |    2 | BE: 18599 vs 15870, LE: 42824 vs 65085 |
|   5 | 0x03634 | 0x03635 |    2 | BE: 25935 vs 33512, LE: 20325 vs 59522 |
|   6 | 0x0371D | 0x0371E |    2 | BE: 5452 vs 4956, LE: 19477 vs 23571 |
|   7 | 0x03929 | 0x0392A |    2 | BE: 2793 vs 2349, LE: 59658 vs 11529 |
|   8 | 0x03937 | 0x03938 |    2 | BE: 21756 vs 36442, LE: 64596 vs 23182 |
|   9 | 0x03991 | 0x03991 |    1 | 18k: 8d flex: 86 |
|  10 | 0x03C3A | 0x03C3B |    2 | BE: 52129 vs 48474, LE: 41419 vs 23229 |
|  11 | 0x03F3D | 0x03F3E |    2 | BE: 34711 vs 24624, LE: 38791 vs 12384 |
|  12 | 0x041A5 | 0x041A5 |    1 | 18k: 15 flex: 24 |
|  13 | 0x041F1 | 0x041F1 |    1 | 18k: ef flex: fe |
|  14 | 0x04240 | 0x04241 |    2 | BE: 16875 vs 45377, LE: 60225 vs 16817 |
|  15 | 0x04288 | 0x04288 |    1 | 18k: 70 flex: 7f |
|  16 | 0x04296 | 0x04296 |    1 | ASCII: '^' vs 'm' |
|  17 | 0x0429E | 0x0429E |    1 | ASCII: 'Z' vs 'i' |
|  18 | 0x042EA | 0x042EA |    1 | 18k: 0a flex: 0e |
|  19 | 0x042FB | 0x042FC |    2 | BE: 25886 vs 25093, LE: 7781 vs 1378 |
|  20 | 0x04300 | 0x04320 |   33 |  |
|  21 | 0x04325 | 0x04344 |   32 |  |
|  22 | 0x04348 | 0x04348 |    1 | 18k: 6b flex: ad |
|  23 | 0x0434A | 0x0434A |    1 | 18k: 05 flex: 36 |
|  24 | 0x0434C | 0x0434C |    1 | 18k: 18 flex: 27 |
|  25 | 0x0434E | 0x0434E |    1 | 18k: 05 flex: 36 |
|  26 | 0x04350 | 0x0436E |   31 |  |
|  27 | 0x04372 | 0x04372 |    1 | ASCII: 'w' vs 'k' |
|  28 | 0x04374 | 0x043A1 |   46 |  |
|  29 | 0x043A3 | 0x043A7 |    5 | 18k: e274008877 flex: 5b20e80f0e |
|  30 | 0x043A9 | 0x043B0 |    8 | 18k: 77007700761f0479 flex: e274000877007700 |
|  31 | 0x043B2 | 0x043B7 |    6 | 18k: 030004e851e0 flex: c4032a7700e7 |
|  32 | 0x043B9 | 0x043C5 |   13 |  |
|  33 | 0x043C7 | 0x043CA |    4 | 18k: 9a019b09 flex: 77007700 |
|  34 | 0x043CC | 0x04410 |   69 |  |
|  35 | 0x04413 | 0x0441C |   10 |  |
|  36 | 0x04420 | 0x0442C |   13 |  |
|  37 | 0x0442E | 0x0442E |    1 | 18k: 22 flex: 14 |
|  38 | 0x04431 | 0x04458 |   40 |  |
|  39 | 0x0445A | 0x04474 |   27 |  |

## Power Rating Value Search

  5000 (5kW common limit) in 18kPV: LE at [], BE at ['0x1062A', '0x15072', '0x150A4', '0x166B8', '0x166EA']
  5000 (5kW common limit) in FlexBOSS: LE at [], BE at ['0x10327', '0x14D6F', '0x14DA1', '0x163B5', '0x163E7']
  6000 (6000XP rated power) in 18kPV: LE at [], BE at ['0x0FEA1', '0x10680', '0x10FED', '0x10FFF', '0x1C2C0']
  6000 (6000XP rated power) in FlexBOSS: LE at [], BE at ['0x0FB9E', '0x1037D', '0x10CEA', '0x10CFC', '0x1BFBD']
  12000 (12kPV rated power) in 18kPV: LE at [], BE at ['0x17D99', '0x35486']
  12000 (12kPV rated power) in FlexBOSS: LE at [], BE at ['0x17A96', '0x35175', '0x38957', '0x38990', '0x389C6']
  15000 (15kW AC charge max) in 18kPV: LE at [], BE at ['0x0FFB9', '0x1AF50', '0x1F238', '0x1FB19', '0x1FB23']
  15000 (15kW AC charge max) in FlexBOSS: LE at [], BE at ['0x0FCB6', '0x1AC4D', '0x1EF35', '0x1F816', '0x1F820']
  18000 (18kPV rated power) in 18kPV: LE at ['0x4408C', '0x440BC', '0x440EC', '0x4411C', '0x442CC'], BE at ['0x054D9', '0x0553F', '0x05589', '0x1AF5E', '0x211AF']
  18000 (18kPV rated power) in FlexBOSS: LE at ['0x439A3', '0x439D3', '0x43A03', '0x43A33', '0x43BE6'], BE at ['0x054F7', '0x0555D', '0x055A7', '0x1AC5B', '0x20EAC']
  21000 (FlexBOSS21 rated power) in 18kPV: LE at ['0x07735', '0x0FB09', '0x14D20', '0x16D3F', '0x18974'], BE at ['0x02374', '0x023BC', '0x03BCC', '0x063F8', '0x065A2']
  21000 (FlexBOSS21 rated power) in FlexBOSS: LE at ['0x07753', '0x0F806', '0x14A1D', '0x16A3C', '0x18671'], BE at ['0x02374', '0x023BC', '0x03BCC', '0x06416', '0x065C0']

## Voltage/Frequency Threshold Search

  2300 (230.0V (÷10, EU L-N)) in 18kPV DSP: 6 hits, first at 0x43BCA, 0x43BDE, 0x43C42, 0x43CCE, 0x43CE2
  2300 (230.0V (÷10, EU L-N)) in FlexBOSS DSP: 6 hits, first at 0x434E4, 0x434F8, 0x4355C, 0x435E8, 0x435FC
  2400 (240.0V (÷10, US split-phase)) in 18kPV DSP: 76 hits, first at 0x063C6, 0x066B1, 0x07D1E, 0x07F51, 0x080CD
  2400 (240.0V (÷10, US split-phase)) in FlexBOSS DSP: 76 hits, first at 0x063E4, 0x066CF, 0x07D3C, 0x07F6F, 0x080EB
  4160 (416.0V (÷10, bus voltage)) in 18kPV DSP: 4 hits, first at 0x1A36A, 0x35A12, 0x3A938, 0x3CDE2
  4160 (416.0V (÷10, bus voltage)) in FlexBOSS DSP: 4 hits, first at 0x1A067, 0x35701, 0x3A627, 0x3CA5F
  4800 (48.0V (÷10, battery nominal)) in 18kPV DSP: 6 hits, first at 0x16FAD, 0x44132, 0x44152, 0x44162, 0x441F2
  4800 (48.0V (÷10, battery nominal)) in FlexBOSS DSP: 6 hits, first at 0x16CAA, 0x43A4C, 0x43A6C, 0x43A7C, 0x43B0C
  5200 (52.0V (÷10, battery float)) in 18kPV DSP: 4 hits, first at 0x08B87, 0x08BE3, 0x08C3B, 0x08C57
  5200 (52.0V (÷10, battery float)) in FlexBOSS DSP: 1 hits, first at 0x08C57
