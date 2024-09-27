#include "utils/sim.h"

#include <stdint.h>

// TODO remove  || defined(TB_FORCE_USE_MERGED) once intrinsics support is no longer WIP
#if __has_builtin(__builtin_riscv_merged_ijmp) || defined(TB_FORCE_USE_MERGED)
#define ASM_PREFIX "MERGED"
#define __builtin_riscv_ijmp __builtin_riscv_merged_ijmp
#else
#define ASM_PREFIX "INDIRECTJMP"
#define __builtin_riscv_ijmp __builtin_riscv_indirectjmp_ijmp
#endif

void abortMission42() {
  auto resData = getResultPtr();
  *resData = 42;
  return; // NOTE THIS WONT RETURN TO THE MAIN FUNCTION BUT INSTEAD EXIT THE PROGRAM
}

int main() {

  auto *funAddr = abortMission42;
  auto addr = &funAddr;
  // Increment 'res' using RISC-V inline assembly
  asm volatile(
      ASM_PREFIX ".ijmp %0, 0\n" // Jump into the abortMission42 function
      : "+r"(addr)        // Output operand: 'res' will be modified
  );

  auto resData = getResultPtr();
  *resData = -1;
  
  return 0;
}
