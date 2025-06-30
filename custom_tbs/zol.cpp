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
  // TODO FIXME: Yeah the builtin does not really work as expected and wrong
  // assembly is generated... so we will rely on inline assembly instead!
  //__builtin_riscv_setupzol(/*Since we wrote our "loop" in inline assembly, we
  //                           know that it consists of a single instruction,
  //                           hence ZOLENDPC = ZOLSTARTPC + 4 = PC + 8 = PC + (4
  //                           << 1)*/
  //                          4,
  //                          ITERATIONS - 1);
  // Increment 'res' using RISC-V inline assembly
  // Note: ZOL (specifically for CVA6) currently has some limitations with compressed instructions
  // - loop end PC (END_PC) must appear in the fetch stage
  // -> loop end must be 4-byte aligned, otherwise the core will request END_PC-2 and END_PC+2 and then realign
  // - loop body must not contain compressed instructions
  // -> hardware assumes only one instruction leaves the realigner at a time
  asm volatile(
      ".p2align 2\n" //Enforce 32bit alignment for the ZOL setup instruction (may insert nop)
      ASM_PREFIX ".setupzol 4, 41\n" // Initialize the loop
                                     // - first arg: PC offset to one-past-end instruction divided by 2
                                     // - second arg: iteration count -1
                                     // note: args may be flipped in different assembler integrations
      ".word 0x00158593\n"   // RISC-V uncompressed instruction to add immediate value 1 to a1
      //"addi a1, a1, 1\n"
      "addi %0, a1, 100\n" // RISC-V instruction to add immediate value 100 to res
                           // (outside the loop, executed once)
      : "+r"(res)          // Output operand: 'res' will be modified
      : //No input operands
      : "a1"
  );
  auto resData = getResultPtr();
  *resData = res;

  return 0;
}
