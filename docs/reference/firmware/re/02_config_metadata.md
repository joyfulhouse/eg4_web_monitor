# Config Metadata Analysis (0x021-0x03D)
# Region size: 29 bytes

## Raw Bytes
```
  fe 02 8f 00 de 00 8f 48 12 59 a8 42 8f 08 02 00 76 48 14 6c 76 40 e1 34 fe 82 00 06 ff
```

## Parsed as 16-bit LE words
| Offset | Hex | Decimal | Notes |
|--------|-----|---------|-------|
| 0x021 (+ 0) | 0x02FE |   766 | First byte pair: 0xFE 0x02 |
| 0x023 (+ 2) | 0x008F |   143 |  |
| 0x025 (+ 4) | 0x00DE |   222 | 222 decimal - possible register count or size |
| 0x027 (+ 6) | 0x488F | 18575 |  |
| 0x029 (+ 8) | 0x5912 | 22802 |  |
| 0x02B (+10) | 0x42A8 | 17064 |  |
| 0x02D (+12) | 0x088F |  2191 |  |
| 0x02F (+14) | 0x0002 |     2 |  |
| 0x031 (+16) | 0x4876 | 18550 |  |
| 0x033 (+18) | 0x6C14 | 27668 |  |
| 0x035 (+20) | 0x4076 | 16502 |  |
| 0x037 (+22) | 0x34E1 | 13537 |  |
| 0x039 (+24) | 0x82FE | 33534 |  |
| 0x03B (+26) | 0x0600 |  1536 |  |

## Parsed as 16-bit BE words
| Offset | Hex | Decimal | Notes |
|--------|-----|---------|-------|
| 0x021 (+ 0) | 0xFE02 | 65026 | Possible config version |
| 0x023 (+ 2) | 0x8F00 | 36608 |  |
| 0x025 (+ 4) | 0xDE00 | 56832 |  |
| 0x027 (+ 6) | 0x8F48 | 36680 |  |
| 0x029 (+ 8) | 0x1259 |  4697 |  |
| 0x02B (+10) | 0xA842 | 43074 |  |
| 0x02D (+12) | 0x8F08 | 36616 |  |
| 0x02F (+14) | 0x0200 |   512 |  |
| 0x031 (+16) | 0x7648 | 30280 |  |
| 0x033 (+18) | 0x146C |  5228 |  |
| 0x035 (+20) | 0x7640 | 30272 |  |
| 0x037 (+22) | 0xE134 | 57652 |  |
| 0x039 (+24) | 0xFE82 | 65154 |  |
| 0x03B (+26) | 0x0006 |     6 |  |

## Magic Byte Analysis

Header at 0x000: `00 00 48 14 59` (known magic)
Config at 0x021: starts with `fe 02 8f 00 de 00`

Notable patterns:
- Bytes 0x027-0x02A: `48 12 59 A8` — variant of header magic `48 14 59`
  (0x4812 vs 0x4814 differ by 2, possibly config vs app identifier)
- Byte 0x031: `48 14` — exact header magic fragment
- Region 0xFF padding fills 0x005-0x020 and 0x03E-0x0403

## Field Hypothesis
```
  Offset 0x021: 0xFE = 254  — FF padding end marker?
  Offset 0x022: 0x02 = 2    — Config format version major?
  Offset 0x023: 0x8F = 143  — Config type/category (0x02=Para)?
  Offset 0x024: 0x00 = 0    — Config sub-version?
  Offset 0x025: 0xDE = 222  — Padding/zero
  Offset 0x026: 0x00 = 0    — Block count or size field (222)?
  Offset 0x027: 0x8F = 143  — Padding/zero
  Offset 0x028-0x02B: Config magic `48 12 59 a8`
  Offset 0x02C-0x02F: `42 8f 08 02` — Checksum/flags?
  Offset 0x030-0x033: `00 76 48 14` — Section offsets?
  Offset 0x034-0x037: `6c 76 40 e1` — App magic + version?
  Offset 0x038-0x03B: `34 fe 82 00` — Checksums?
  Offset 0x03C-0x03D: `06 ff` — Terminal?
```
