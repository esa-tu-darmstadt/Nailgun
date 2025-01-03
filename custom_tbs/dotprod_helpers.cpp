#include "dotprod_helpers.h"

void init_arrays(int8_t *in1, int8_t *in2, unsigned *expected, unsigned size){
  for (unsigned i = 0; i < size; ++i) {
    in1[i] = i;
    in2[i] = size - 1 - i;
  }
  for (unsigned i = 0; i < size; i += 4) {
    int32_t mul1 = static_cast<int16_t>(in1[i]) * static_cast<int16_t>(in2[i]);
    int32_t mul2 =
        static_cast<int16_t>(in1[i + 1]) * static_cast<int16_t>(in2[i + 1]);
    int32_t mul3 =
        static_cast<int16_t>(in1[i + 2]) * static_cast<int16_t>(in2[i + 2]);
    int32_t mul4 =
        static_cast<int16_t>(in1[i + 3]) * static_cast<int16_t>(in2[i + 3]);
    expected[i / 4] = mul1 + mul2 + mul3 + mul4;
  }    
}
