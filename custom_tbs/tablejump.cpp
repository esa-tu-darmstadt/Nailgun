#include "utils/sim.h"

#include <stdint.h>

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

  // jump to each function once
  for (int i = 0; i < NUM_OF_JUMP_TARGETS; i++) {
    // use inline assembly here to pin the result register to the link register
    asm volatile (
        ".insn i 0x2B, 2, x1, x0, %0"
        :
        : "i"(i)
        : "x1"
    );
  }

  return 0;
}
