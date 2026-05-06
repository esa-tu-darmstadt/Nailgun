#include "utils/sim.h"

#include <stdint.h>

#if __has_builtin(__builtin_riscv_merged_mac)
#define __builtin_riscv_mac __builtin_riscv_merged_mac
#else
#define __builtin_riscv_mac __builtin_riscv_mac_mac
#endif

int32_t mac(int32_t initialAcc, int32_t *data, unsigned length) {
  int32_t acc = initialAcc;
  for (unsigned i = 0; i < length; i += 2) {
    acc += data[i] * data[i + 1];
  }
  return acc;
}

int main() {

#define ARR_SIZE 100
  int32_t data[ARR_SIZE];

  // Initialize our test data
  for (unsigned i = 0; i < (ARR_SIZE); ++i) {
    data[i] = i;
  }

  auto initialAcc = 42;
  auto expectedRes = mac(initialAcc, data, ARR_SIZE);

  // Test mac:
  int32_t acc = initialAcc;
  for (unsigned i = 0; i < (ARR_SIZE); i += 2) {
    __builtin_riscv_mac(acc, data[i], data[i + 1]);
  }
  auto resData = getResultPtr();
  *resData = expectedRes - acc;

  return 0;
}
