#include "utils/sim.h"

#if __has_builtin(__builtin_riscv_merged_setupzol)
#define ASM_PREFIX "MERGED"
#define __builtin_riscv_setupzol __builtin_riscv_merged_setupzol
#else
#define ASM_PREFIX "ZOL"
#define __builtin_riscv_setupzol __builtin_riscv_zol_setupzol
#endif

int main() {

  constexpr unsigned ITERATIONS = 42;
  unsigned res = 0;
  // Asm format: MERGED.setupzol $uimmL, $uimmS
  //   uimmL (12-bit): iteration count - 1
  //   uimmS (5-bit): PC offset to one-past-end instruction divided by 2
  // Note: ZOL (specifically for CVA6) currently has some limitations with compressed instructions
  // - loop end PC (END_PC) must appear in the fetch stage
  // -> loop end must be 4-byte aligned, otherwise the core will request END_PC-2 and END_PC+2 and then realign
  // - loop body must not contain compressed instructions
  // -> hardware assumes only one instruction leaves the realigner at a time
  asm volatile(
      ".option push\n"
      ".option norvc\n"   // Compressed instructions break the hardcoded offset
      ".p2align 3\n" // Enforce 64bit alignment
                     // -> Set so the instr >after the loop end< is 64bit aligned
      ASM_PREFIX ".setupzol 41, 4\n" // Initialize the loop
                                     // - first arg (uimmL): iteration count - 1
                                     // - second arg (uimmS): PC offset / 2
      "addi a1, a1, 1\n"
      "addi %0, a1, 100\n" // RISC-V instruction to add immediate value 100 to res
                           // (outside the loop, executed once)
      ".option pop\n"
      : "+r"(res)          // Output operand: 'res' will be modified
      : //No input operands
      : "a1"
  );
  auto resData = getResultPtr();
  *resData = res;

  return 0;
}
