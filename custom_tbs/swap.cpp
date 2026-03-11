#include "utils/sim.h"

#include <stdint.h>

#if __has_builtin(__builtin_riscv_merged_swapnmac)
#define __builtin_riscv_swap_n_mac __builtin_riscv_merged_swapnmac
#else
#define __builtin_riscv_swap_n_mac __builtin_riscv_swap_swapnmac
#endif

int main() {
  auto resData = getResultPtr();

  // Test 1: Individual calls — store raw results
  // swap_n_mac(rd, rs1, rs2): rd += rs1*rs2, swap(rs1, rs2)
  int acc = 0, a, b;

  a = 3; b = 7;
  __builtin_riscv_swap_n_mac(acc, a, b); // acc = 0 + 3*7 = 21
  *resData++ = acc;

  a = 4; b = 5;
  __builtin_riscv_swap_n_mac(acc, a, b); // acc = 21 + 4*5 = 41
  *resData++ = acc;

  a = 10; b = 10;
  __builtin_riscv_swap_n_mac(acc, a, b); // acc = 41 + 100 = 141
  *resData++ = acc;

  // Test 2: Zero multiplication
  a = 0; b = 12345;
  __builtin_riscv_swap_n_mac(acc, a, b); // acc = 141 + 0 = 141
  *resData++ = acc;

  // Test 3: 32-bit overflow
  acc = 5; a = 0xFFFF; b = 0xFFFF;
  __builtin_riscv_swap_n_mac(acc, a, b); // acc = 5 + 0xFFFE0001 = 0xFFFE0006
  *resData++ = acc;

  // Test 4: Accumulation loop
  {
#define ARR_SIZE 100
    int data[ARR_SIZE];
    for (unsigned i = 0; i < ARR_SIZE; i++)
      data[i] = i;

    int initialAcc = 42;
    int expectedRes = initialAcc;
    for (unsigned i = 0; i < ARR_SIZE; i += 2)
      expectedRes += data[i] * data[i + 1];

    acc = initialAcc;
    for (unsigned i = 0; i < ARR_SIZE; i += 2) {
      a = data[i]; b = data[i + 1];
      __builtin_riscv_swap_n_mac(acc, a, b);
    }

    *resData++ = expectedRes - acc; // Should be 0
  }

  *resData++ = 0xFFFFFFFF; // Sentinel

  return 0;
}
