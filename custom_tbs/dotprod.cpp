#include "utils/sim.h"

#include <stdint.h>

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
  for (unsigned i = 0; i < (ARR_SIZE); ++i) {
    in1[i] = i;
    in2[i] = (ARR_SIZE)-1 - i;
  }
  for (unsigned i = 0; i < (ARR_SIZE); i += 4) {
    int32_t mul1 = static_cast<int16_t>(in1[i]) * static_cast<int16_t>(in2[i]);
    int32_t mul2 =
        static_cast<int16_t>(in1[i + 1]) * static_cast<int16_t>(in2[i + 1]);
    int32_t mul3 =
        static_cast<int16_t>(in1[i + 2]) * static_cast<int16_t>(in2[i + 2]);
    int32_t mul4 =
        static_cast<int16_t>(in1[i + 3]) * static_cast<int16_t>(in2[i + 3]);
    expected[i / 4] = mul1 + mul2 + mul3 + mul4;
  }

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
