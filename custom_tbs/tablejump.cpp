#include "utils/sim.h"

#include <stdint.h>

// TODO remove  || defined(TB_FORCE_USE_MERGED) once intrinsics support is no longer WIP
#if __has_builtin(__builtin_riscv_merged_jalt) || defined(TB_FORCE_USE_MERGED)
#define ASM_PREFIX "MERGED"
#else
#define ASM_PREFIX "TABLEJUMP"
#endif

#if __has_builtin(__builtin_riscv_merged_setjumptableaddr)
#define __builtin_riscv_set_addr __builtin_riscv_merged_setjumptableaddr
#else
#define __builtin_riscv_set_addr __builtin_riscv_tablejump_setjumptableaddr
#endif
#if __has_builtin(__builtin_riscv_merged_jalt)
#define __builtin_riscv_jalt __builtin_riscv_merged_jalt
#else
#define __builtin_riscv_jalt __builtin_riscv_tablejump_jalt
#endif

#define NUM_OF_JUMP_TARGETS 64

static unsigned *resData = nullptr;

// actual target function template
template<int N>
static void funct() {
    *(resData++) = N+1;
}

// Recursive template to generate a function jump table
template<int N>
struct FillFunctPtrs {
    static void fill(void (**arr)()) {
        FillFunctPtrs<N-1>::fill(arr);
        arr[N-1] = &funct<N-1>;
    }
};
// Base case for recursive template
template<>
struct FillFunctPtrs<0> {
    static void fill(void (**arr)()) { }
};

int main() {
  // Array used as jump table
  void (*funct_ptrs[NUM_OF_JUMP_TARGETS])();
  // populate jump table
  FillFunctPtrs<NUM_OF_JUMP_TARGETS>::fill(funct_ptrs);

  // get result ptr
  resData = getResultPtr();

  // send jump table address to ISAX
  __builtin_riscv_set_addr(reinterpret_cast<intptr_t>(funct_ptrs));

  // jump to each function once (unrolled — jalt requires compile-time immediate)
  // Asm format: MERGED.jalt $simm, $rd — encoding order: simm (12-bit index), rd (link register)
#define JALT(idx) asm volatile (ASM_PREFIX ".jalt " #idx ", x1" ::: "x1")
  JALT(0);  JALT(1);  JALT(2);  JALT(3);  JALT(4);  JALT(5);  JALT(6);  JALT(7);
  JALT(8);  JALT(9);  JALT(10); JALT(11); JALT(12); JALT(13); JALT(14); JALT(15);
  JALT(16); JALT(17); JALT(18); JALT(19); JALT(20); JALT(21); JALT(22); JALT(23);
  JALT(24); JALT(25); JALT(26); JALT(27); JALT(28); JALT(29); JALT(30); JALT(31);
  JALT(32); JALT(33); JALT(34); JALT(35); JALT(36); JALT(37); JALT(38); JALT(39);
  JALT(40); JALT(41); JALT(42); JALT(43); JALT(44); JALT(45); JALT(46); JALT(47);
  JALT(48); JALT(49); JALT(50); JALT(51); JALT(52); JALT(53); JALT(54); JALT(55);
  JALT(56); JALT(57); JALT(58); JALT(59); JALT(60); JALT(61); JALT(62); JALT(63);
#undef JALT

  return 0;
}
