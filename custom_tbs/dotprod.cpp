#include "utils/sim.h"

#include "dotprod_helpers.h"

#if __has_builtin(__builtin_riscv_merged_dotp)
#define __builtin_riscv_dotp __builtin_riscv_merged_dotp
#else
#define __builtin_riscv_dotp __builtin_riscv_dotprod_dotp
#endif

int main() {

#define ARR_SIZE 256
  int8_t in1[ARR_SIZE];
  int8_t in2[ARR_SIZE];

  unsigned expected[(ARR_SIZE) / 4];

  // Initialize the test arrays
  init_arrays(in1, in2, expected, ARR_SIZE);

  // Perform the test
  auto resData = getResultPtr();
  for (unsigned i = 0; i < sizeof(expected) / sizeof(expected[0]); ++i) {
    auto res = __builtin_riscv_dotp(reinterpret_cast<uint32_t *>(in1)[i],
                                    reinterpret_cast<uint32_t *>(in2)[i]);
    auto expectedRes = expected[i];
    *resData = expectedRes - res + i;
    ++resData;
  }

  return 0;
}
