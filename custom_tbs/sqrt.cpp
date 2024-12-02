#include "utils/sim.h"

#include <stdint.h>

#if (__has_builtin(__builtin_riscv_merged_sqrt_decoupled) || defined(TB_FORCE_USE_MERGED)) && !defined(TB_USE_SQRT_STALL)
#define __builtin_riscv_sqrt __builtin_riscv_merged_sqrt_decoupled
#elif __has_builtin(__builtin_riscv_merged_sqrt_stall) || defined(TB_FORCE_USE_MERGED)
#define __builtin_riscv_sqrt __builtin_riscv_merged_sqrt_stall
#elif __has_builtin(__builtin_riscv_sqrt_stall_sqrt_stall)
#define __builtin_riscv_sqrt __builtin_riscv_sqrt_stall_sqrt_stall
#else
#define __builtin_riscv_sqrt __builtin_riscv_sqrt_sqrt_decoupled
#endif


// Source: https://github.com/chmike/fpsqrt/blob/master/fpsqrt.c
// Int to fixed point sqrt implementation
int32_t sw_sqrt(int32_t v) {
  uint32_t r = v;
  uint32_t b = 0x40000000;
  uint32_t q = 0;
  for (int i = 0; i < 32; ++i) {
    uint32_t t = q + b;
    if (r >= t) {
      r -= t;
      q = t + b;
    }
    r <<= 1;
    b >>= 1;
  }
  if (r > q)
    ++q;
  return q;
}

int main() {
  auto resData = getResultPtr();

  // Compare results of the ISAX with a software implementation
  for (unsigned i = 0; i < 100; ++i) {
    int32_t res1 = __builtin_riscv_sqrt(i);
    int32_t res2 = sw_sqrt(i);
    *resData = res1 - res2;
    ++resData;
  }

  return 0;
}
