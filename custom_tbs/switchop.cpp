#include "utils/sim.h"

#include <stdint.h>

// switchop: a runtime-selected ALU. The low 3 bits of the second operand pick
// the operation that is applied to both operands. The custom instruction is
// implemented with a CoreDSL `switch` statement, so this testbench exercises
// the switch-statement legalization path (CoreDSLLegalizeCF).

#if __has_builtin(__builtin_riscv_merged_switchop) || defined(TB_FORCE_USE_MERGED)
#define __builtin_riscv_switchop __builtin_riscv_merged_switchop
#else
#define __builtin_riscv_switchop __builtin_riscv_switchop_switchop
#endif

// Pure software model of SWITCHOP, mirroring the CoreDSL behavior exactly.
static uint32_t switchop_ref(uint32_t a, uint32_t b) {
  unsigned sel = b & 0x7u;
  switch (sel) {
  case 0:
    return a + b;
  case 1:
    return a - b;
  case 2:
    return a & b;
  case 3:
    return a | b;
  case 4:
    return a ^ b;
  case 5:
    return a << (b & 31u);
  case 6:
    return a >> (b & 31u);
  default:
    return a;
  }
}

int main() {
  // (a, b) test vectors. The low 3 bits of b select the operation, so these
  // cover every case (add/sub/and/or/xor/shl/shr) plus the default branch.
  struct {
    uint32_t a, b;
  } vecs[] = {
      {0x12345678u, 0x00000010u}, // sel 0: add  (b&7 == 0)
      {0x12345678u, 0x00000009u}, // sel 1: sub  (b&7 == 1)
      {0xFF00FF00u, 0x0F0F0F0Au}, // sel 2: and  (b&7 == 2)
      {0x0000FFFFu, 0xFFFF0003u}, // sel 3: or   (b&7 == 3)
      {0xAAAAAAAAu, 0x5555555Cu}, // sel 4: xor  (b&7 == 4)
      {0x00000001u, 0x00000005u}, // sel 5: shl by 5  (b&7 == 5)
      {0x80000000u, 0x0000000Eu}, // sel 6: shr by 14 (b&7 == 6)
      {0xDEADBEEFu, 0x0000000Fu}, // sel 7: default   (b&7 == 7)
  };

  auto resData = getResultPtr();

  for (auto v : vecs) {
    uint32_t expected = switchop_ref(v.a, v.b);
    uint32_t hw = __builtin_riscv_switchop(v.a, v.b);
    // Store the difference; a correct implementation yields 0 for every vector.
    *resData++ = expected - hw;
  }

  *resData++ = 0xFFFFFFFFu; // Sentinel

  return 0;
}
