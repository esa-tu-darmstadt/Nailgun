#include "utils/sim.h"

#include <stdint.h>

#if __has_builtin(__builtin_riscv_merged_set_addr)
#define __builtin_riscv_set_addr __builtin_riscv_merged_set_addr
#else
#define __builtin_riscv_set_addr __builtin_riscv_autoinc_set_addr
#endif
#if __has_builtin(__builtin_riscv_merged_lw_inc)
#define __builtin_riscv_lw_inc __builtin_riscv_merged_lw_inc
#else
#define __builtin_riscv_lw_inc __builtin_riscv_autoinc_lw_inc
#endif
#if __has_builtin(__builtin_riscv_merged_sw_inc)
#define __builtin_riscv_sw_inc __builtin_riscv_merged_sw_inc
#else
#define __builtin_riscv_sw_inc __builtin_riscv_autoinc_sw_inc
#endif

int main() {

#define ARR_SIZE 100
  unsigned data[ARR_SIZE];

  // Initialize our test data
  for (unsigned i = 0; i < (ARR_SIZE); ++i) {
    data[i] = i;
  }

  auto resData = getResultPtr();
  // Test sw_inc:
  __builtin_riscv_set_addr(reinterpret_cast<intptr_t>(resData));
  for (auto d : data) {
    __builtin_riscv_sw_inc(d, sizeof(d));
  }
  resData += ARR_SIZE;

  // Test lw_inc
  __builtin_riscv_set_addr(reinterpret_cast<intptr_t>(data));
  for (unsigned i = 0; i < (ARR_SIZE); ++i) {
    auto d = __builtin_riscv_lw_inc(sizeof(*data));
    *resData = d;
    ++resData;
  }

  return 0;
}
