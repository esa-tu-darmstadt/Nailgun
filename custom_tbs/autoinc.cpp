#include "utils/sim.h"

#include <stdint.h>

#if __has_builtin(__builtin_riscv_merged_setaddr)
#define __builtin_riscv_set_addr __builtin_riscv_merged_setaddr
#else
#define __builtin_riscv_set_addr __builtin_riscv_autoinc_setaddr
#endif
#if __has_builtin(__builtin_riscv_merged_lwinc)
#define __builtin_riscv_lw_inc __builtin_riscv_merged_lwinc
#else
#define __builtin_riscv_lw_inc __builtin_riscv_autoinc_lwinc
#endif
#if __has_builtin(__builtin_riscv_merged_swinc)
#define __builtin_riscv_sw_inc __builtin_riscv_merged_swinc
#else
#define __builtin_riscv_sw_inc __builtin_riscv_autoinc_swinc
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
