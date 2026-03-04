#include "utils/sim.h"

#if __has_builtin(__builtin_riscv_merged_complexadd) ||                        \
    defined(TB_FORCE_USE_MERGED)
#define __builtin_riscv_complexadd __builtin_riscv_merged_complexadd
#define __builtin_riscv_complexmul __builtin_riscv_merged_complexmul
#else
#define __builtin_riscv_complexadd __builtin_riscv_complex_complexadd
#define __builtin_riscv_complexmul __builtin_riscv_complex_complexmul
#endif

// Pack two 16-bit signed components into one 32-bit complex number.
// Upper 16 bits = real, lower 16 bits = imaginary.
static int pack(int real, int imag) { return (real << 16) | (imag & 0xFFFF); }

int main() {
  auto resData = getResultPtr();

  // complexadd: (-3+2i) + (45+40i) = (42+42i)
  resData[0] = __builtin_riscv_complexadd(pack(-3, 2), pack(45, 40));
  resData++;

  // Two complexadds: (-42-42i)+(21+42i), (-5-128i)+(32767-256i)
  resData[0] = __builtin_riscv_complexadd(pack(-42, -42), pack(21, 42));
  resData[1] = __builtin_riscv_complexadd(pack(-5, -128), pack(32767, -256));
  resData += 2;

  // Register conflict: result of first add feeds into second
  // r1 = complexadd(10-128i, 11+128i) = (21+0i)
  // r2 = complexadd(r1, 21+42i) = (42+42i)
  {
    int r1 = __builtin_riscv_complexadd(pack(10, -128), pack(11, 128));
    int r2 = __builtin_riscv_complexadd(r1, pack(21, 42));
    resData[0] = r1;
    resData[1] = r2;
    resData += 2;
  }

  // complexmul + complexadd
  // (-42-42i)*(21-42i) = (-2646+882i)
  // (-32768+0i)+(32767-256i) = (-1-256i)
  resData[0] = __builtin_riscv_complexmul(pack(-42, -42), pack(21, -42));
  resData[1] = __builtin_riscv_complexadd(pack(-32768, 0), pack(32767, -256));
  resData += 2;

  return 0;
}
