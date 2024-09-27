#include "utils/sim.h"

#include <stdint.h>

// TODO remove  || defined(TB_FORCE_USE_MERGED) once intrinsics support is no longer WIP
#if __has_builtin(__builtin_riscv_merged_cv_beqimm) || defined(TB_FORCE_USE_MERGED)
#define ASM_PREFIX "MERGED"
#define __builtin_riscv_cv_beqimm __builtin_riscv_merged_cv_beqimm
#else
#define ASM_PREFIX "BRIMM"
#define __builtin_riscv_cv_beqimm __builtin_riscv_brimm_cv_beqimm
#endif

int main() {

  unsigned res = 1;

  /* TODO well this is super ugly... the imm value must be split manually ...
    "BRIMM.cv_beqimm", "$TREENAIL_WAS_HERE_imm12_10_10, $TREENAIL_WAS_HERE_imm12_3_0, $TREENAIL_WAS_HERE_rs1_4_0, $TREENAIL_WAS_HERE_imm5_4_0, $TREENAIL_WAS_HERE_imm12
_9_4, $TREENAIL_WAS_HERE_imm12_11_11",
*/
  asm volatile(
      ASM_PREFIX ".cv_beqimm 0, 8, %0, 1, 0, 0\n" // Jump to the last addi command
      "addi %0, %0, 1\n" // RISC-V instruction to add immediate value 1 to res
      "addi %0, %0, 2\n" // RISC-V instruction to add immediate value 1 to res
      "addi %0, %0, 3\n" // RISC-V instruction to add immediate value 1 to res
      "addi %0, %0, 41\n" // RISC-V instruction to add immediate value 1 to res
      : "+r"(res)        // Output operand: 'res' will be modified
  );
  auto resData = getResultPtr();
  *resData = res;

  return 0;
}
