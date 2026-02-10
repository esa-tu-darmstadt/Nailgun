#include "utils/sim.h"

#include <stdint.h>

#if __has_builtin(__builtin_riscv_merged_memset)
#define __builtin_riscv_memset __builtin_riscv_merged_memset
#else
#define __builtin_riscv_memset __builtin_riscv_multimemreadwrite_memset
#endif
#if __has_builtin(__builtin_riscv_merged_memadd)
#define __builtin_riscv_memadd __builtin_riscv_merged_memadd
#else
#define __builtin_riscv_memadd __builtin_riscv_multimemreadwrite_memadd
#endif
#if __has_builtin(__builtin_riscv_merged_memcpy)
#define __builtin_riscv_memcpy __builtin_riscv_merged_memcpy
#else
#define __builtin_riscv_memcpy __builtin_riscv_multimemreadwrite_memcpy
#endif

int main() {
  auto resData = getResultPtr();

  // Test memset
  __builtin_riscv_memset(reinterpret_cast<intptr_t>(resData), 42);
  // Test memcpy
  __builtin_riscv_memcpy(reinterpret_cast<intptr_t>(resData), reinterpret_cast<intptr_t>(resData + 8));
  // Test memadd
  auto res = __builtin_riscv_memadd(reinterpret_cast<intptr_t>(resData));
  resData[16] = res;

  return 0;
}
