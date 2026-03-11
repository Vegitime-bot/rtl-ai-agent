# Demo AES Micro-Architecture

## 1. Overview
- 10 round AES core
- Latency: 12 cycles max

## 2. MixColumns Unit
- Skip MixColumns for rounds >= 5 to reduce power.
- Insert data masking stage before output register.

## 3. Interface Requirements
- Input valid must be high for exactly one cycle per block.
- Output valid asserted when round counter==10.
