# ISAX Encodings Overview

| Custom Space | Instruction Set   | Instruction          | Encoding Mask                      |
| ------------ | ----------------- | -------------------- | ---------------------------------- |
|              |                   |                      | `funct7/\rs2/\rs1/fn3\rd /\opcode` |
| custom-0     | brimm             | cv_beqimm            | `-----------------100-----0001011` |
| custom-0     | zol               | setup_zol            | `-----------------101000000001011` |
| custom-0     | sqrt_stall        | sqrt_stall           | `000010100000-----000-----0001011` |
| custom-0     | sqrt              | sqrt_decoupled       | `000011000000-----000-----0001011` |
| custom-0     | tablejump         | set_jump_table_addr  | `000000000000-----000-----0001011` |
| custom-0     | dotprod           | DOTP                 | `0001001----------000-----0001011` |
| custom-0     | PushPop           | CM__PUSH             | `110000------00000000000000001011` |
| custom-0     | PushPop           | CM__POP              | `111000------00000000000000001011` |
| ------------ | ----------------- | -------------------- | ---------------------------------- |
| custom-1     | tablejump         | jalt                 | `------------00000101-----0101011` |
| custom-1     | MultiMemReadWrite | MEMSET               | `0000110----------000-----0101011` |
| custom-1     | sbox              | sbox                 | `000010000000-----000-----0101011` |
| ------------ | ----------------- | -------------------- | ---------------------------------- |
| custom-2     | autoinc           | sw_inc               | `-----------------010-----1011011` |
| custom-2     | MultiMemReadWrite | MEMADD               | `000011000000-----000-----1011011` |
| ------------ | ----------------- | -------------------- | ---------------------------------- |
| custom-3     | indirectjmp       | ijmp                 | `-----------------010-----1111011` |
| custom-3     | autoinc           | lw_inc               | `-----------------011-----1111011` |
| custom-3     | autoinc           | set_addr             | `000000000000-----000-----1111011` |
| custom-3     | MultiMemReadWrite | MEMCPY               | `0000110----------000-----1111011` |
| custom-3     | sparkle           | sparkle_ell          | `0000010----------111-----1111011` |
| custom-3     | sparkle           | sparkle_rcon         | `0000-------------110-----1111011` |
| custom-3     | sparkle           | sparkle_whole_enci_x | `1000-------------110-----1111011` |
| custom-3     | sparkle           | sparkle_whole_enci_y | `1001-------------110-----1111011` |


## Exhausted encoding spaces:
| Custom Space / Opcode | funct3 | Instruction      |
| --------------------- | ------ | ---------------- |
| custom-0 / `0001011`  | `100`  | brimm/cv_beqimm  |
| custom-0 / `0001011`  | `101`  | zol/setup_zol    |
| --------------------- | ------ | ---------------- |
| custom-1 / `0101011`  | `101`  | tablejump/jalt   |
| --------------------- | ------ | ---------------- |
| custom-2 / `1011011`  | `010`  | autoinc/sw_inc   |
| --------------------- | ------ | ---------------- |
| custom-3 / `1111011`  | `011`  | autoinc/lw_inc   |
| custom-3 / `1111011`  | `010`  | indirectjmp/ijmp |
