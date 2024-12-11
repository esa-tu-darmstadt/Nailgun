#include "utils/sim.h"

#if __has_builtin(__builtin_riscv_merged_setup_zol)
#define ASM_PREFIX "MERGED"
#define __builtin_riscv_setup_zol __builtin_riscv_merged_setup_zol
#else
#define ASM_PREFIX "ZOL"
#define __builtin_riscv_setup_zol __builtin_riscv_zol_setup_zol
#endif

int main() {

  constexpr unsigned ITERATIONS = 42;
  unsigned res = 0;
  // TODO FIXME: Yeah the builtin does not really work as expected and wrong
  // assembly is generated... so we will rely on inline assembly instead!
  //__builtin_riscv_setup_zol(/*Since we wrote our "loop" in inline assembly, we
  //                             know that it consists of a single instruction,
  //                             hence ZOLENDPC = ZOLSTARTPC = PC + 4 = PC + (2
  //                             << 1)*/
  //                          2,
  //                          ITERATIONS);
  // Increment 'res' using RISC-V inline assembly
  asm volatile(
      ASM_PREFIX ".setup_zol 4, 41\n" // Initialize the loop
      "addi %0, %0, 1\n"   // RISC-V instruction to add immediate value 1 to res
      "addi %0, %0, 100\n" // RISC-V instruction to add immediate value 100 to res
                           // (outside the loop, executed once)
      : "+r"(res)          // Output operand: 'res' will be modified
  );
  auto resData = getResultPtr();
  *resData = res;

  return 0;
}
