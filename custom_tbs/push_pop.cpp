#include "utils/sim.h"

#include <stdint.h>
#if __has_builtin(__builtin_riscv_merged_cmpush)
#define __builtin_riscv_cm_push __builtin_riscv_merged_cmpush
#else
#define __builtin_riscv_cm_push __builtin_riscv_zcmp_cmpush
#endif
#if __has_builtin(__builtin_riscv_merged_cmpop)
#define __builtin_riscv_cm_pop __builtin_riscv_merged_cmpop
#else
#define __builtin_riscv_cm_pop __builtin_riscv_zcmp_cmpop
#endif

int main() {
  // The stack addresses decrease -> offset the result ptr
  auto *resData = getResultPtr() + 13;

  // Zcmp: push & pop instructions
  asm volatile(
      R"(
        mv x31, x2
        mv x30, %0
        mv x2, %0
        li x27, 27
        li x26, 26
        li x25, 25
        li x24, 24
        li x23, 23
        li x22, 22
        li x21, 21
        li x20, 20
        li x19, 19
        li x18, 18
        li x9,   9
        li x8,   8
        li x1,   1
    )"
      :
      : "r"(resData)
      : "x1", "x2", "x8", "x9", "x18", "x19", "x20", "x21", "x22", "x23", "x24",
        "x25", "x26", "x27", "x30", "x31");
  __builtin_riscv_cm_push(0, 15); // spimm=0, rlist=15

  asm volatile(
      R"(
        li x27, 0
        li x26, 0
        li x25, 0
        li x24, 0
        li x23, 0
        li x22, 0
        li x21, 0
        li x20, 0
        li x19, 0
        li x18, 0
        li x9,  0
        li x8,  0
        li x1,  0
    )"
      :
      :
      : "x1", "x8", "x9", "x18", "x19", "x20", "x21", "x22", "x23", "x24", "x25",
        "x26", "x27");

  __builtin_riscv_cm_pop(0, 15); // spimm=0, rlist=15

  asm volatile(
      R"(
        mv x2, x30
        sw x27, 0(x2)
        sw x26, 4(x2)
        sw x25, 8(x2)
        sw x24, 12(x2)
        sw x23, 16(x2)
        sw x22, 20(x2)
        sw x21, 24(x2)
        sw x20, 28(x2)
        sw x19, 32(x2)
        sw x18, 36(x2)
        sw x9,  40(x2)
        sw x8,  44(x2)
        sw x1,  48(x2)
        mv x2, x31
    )"
      :
      :
      : "x2", "x8", "x9", "x18", "x19", "x20", "x21", "x22", "x23", "x24",
        "x25", "x26", "x27");

  return 0;
}
