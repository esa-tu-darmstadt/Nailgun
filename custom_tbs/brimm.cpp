#include "utils/sim.h"

// TODO remove  || defined(TB_FORCE_USE_MERGED) once intrinsics support is no longer WIP
#if __has_builtin(__builtin_riscv_merged_cvbeqimm) || defined(TB_FORCE_USE_MERGED)
#define ASM_PREFIX "MERGED"
#define __builtin_riscv_cv_beqimm __builtin_riscv_merged_cvbeqimm
#else
#define ASM_PREFIX "BRIMM"
#define __builtin_riscv_cv_beqimm __builtin_riscv_brimm_cvbeqimm
#endif

int main() {

  unsigned res = 1;

  // Asm format: MERGED.cvbeqimm $imm12, $imm5, $rs1
  // imm12: branch offset / 2 (signed 12-bit, actual offset = imm12 * 2)
  // imm5:  immediate comparison value (signed 5-bit), branch if X[rs1] == imm5
  // imm12=8 → offset=16 bytes → skip 3 instructions → land on last addi
  asm volatile(
      ".option push\n"
      ".option norvc\n"   // Compressed instructions break the hardcoded offset
      ASM_PREFIX ".cvbeqimm 8, 1, %0\n" // Branch to last addi if res == 1
      "addi %0, %0, 1\n"  // Skipped by branch
      "addi %0, %0, 2\n"  // Skipped by branch
      "addi %0, %0, 3\n"  // Skipped by branch
      "addi %0, %0, 41\n" // Branch target: res += 41
      ".option pop\n"
      : "+r"(res)         // Output operand: 'res' will be modified
  );
  auto resData = getResultPtr();
  *resData = res;

  return 0;
}
