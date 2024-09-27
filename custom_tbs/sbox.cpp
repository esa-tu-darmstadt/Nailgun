#include "utils/sim.h"

#if __has_builtin(__builtin_riscv_merged_sbox)
#define __builtin_riscv_sbox  __builtin_riscv_merged_sbox
#else
#define __builtin_riscv_sbox  __builtin_riscv_sbox_sbox
#endif

int main() {
  auto resData = getResultPtr();

  unsigned idx = 0;
  unsigned res3 = 0;

  // In blocks of 4, apply sbox on its previous result (start with 0), until the
  // third result equals 0. (works with this particular SBOX, but not in
  // general)
  do {
    auto res1 = __builtin_riscv_sbox(idx);
    auto res2 = __builtin_riscv_sbox(res1);
    res3 = __builtin_riscv_sbox(res2);
    idx = __builtin_riscv_sbox(res3);
    resData[0] = res1;
    resData[1] = res2;
    resData[2] = res3;
    resData[3] = idx;
    resData += 4;
  } while (res3);

  return 0;
}
