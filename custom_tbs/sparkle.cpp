#include "utils/sim.h"
#include <stdint.h>

// ---------------------------------------------------------------------------
// Builtin selection (merged vs. standalone ISAX name)
// ---------------------------------------------------------------------------
#if __has_builtin(__builtin_riscv_merged_sparkleell) || defined(TB_FORCE_USE_MERGED)
#define hw_ell(a, b)         __builtin_riscv_merged_sparkleell((a), (b))
#define hw_rcon(a, imm)      __builtin_riscv_merged_sparklercon((a), (imm))
#define hw_enci_x(a, b, imm) __builtin_riscv_merged_sparklewholeencix((a), (b), (imm))
#define hw_enci_y(a, b, imm) __builtin_riscv_merged_sparklewholeenciy((a), (b), (imm))
#else
#define hw_ell(a, b)         __builtin_riscv_sparkle_sparkleell((a), (b))
#define hw_rcon(a, imm)      __builtin_riscv_sparkle_sparklercon((a), (imm))
#define hw_enci_x(a, b, imm) __builtin_riscv_sparkle_sparklewholeencix((a), (b), (imm))
#define hw_enci_y(a, b, imm) __builtin_riscv_sparkle_sparklewholeenciy((a), (b), (imm))
#endif

// ---------------------------------------------------------------------------
// Software reference implementation (from sparkle.core_desc)
// ---------------------------------------------------------------------------

static const uint32_t RCON[8] = {
    0xB7E15162, 0xBF715880, 0x38B4DA56, 0x324E7738,
    0xBB1185EB, 0x4F7C7B57, 0xCFBFA1C8, 0xC2B3293D,
};
static const unsigned ROT_0[4] = {31, 17, 0, 24};
static const unsigned ROT_1[4] = {24, 17, 31, 16};

static uint32_t rotr32(uint32_t x, unsigned shamt) {
    shamt &= 31;
    return (x >> shamt) | (x << ((32 - shamt) & 31));
}

static uint32_t sw_ell(uint32_t x) {
    return rotr32(x ^ (x << 16), 16);
}

static uint32_t sw_sparkle_ell(uint32_t a, uint32_t b) {
    return sw_ell(a ^ b);
}

static uint32_t sw_rcon(uint32_t a, unsigned imm) {
    return a ^ RCON[imm];
}

static void sw_whole_enc(uint32_t a, uint32_t b, unsigned imm,
                         uint32_t &out_x, uint32_t &out_y) {
    uint32_t ci = RCON[imm];
    for (int k = 0; k < 4; k++) {
        a += rotr32(b, ROT_0[k]);
        b ^= rotr32(a, ROT_1[k]);
        a ^= ci;
    }
    out_x = a;
    out_y = b;
}

// ---------------------------------------------------------------------------
// Tests — each entry writes (hw_result - sw_result); expected output is all 0s
// ---------------------------------------------------------------------------

static constexpr unsigned NUM_TESTS = 28;

int main() {
    auto resData = getResultPtr();
    uint32_t sw_x, sw_y;

    // Pre-fill with 0xDEADBEEF to detect missing stores
    for (unsigned i = 0; i < NUM_TESTS; i++)
        resData[i] = 0xDEADBEEF;

    // -- sparkle_ell: rd = ELL(rs1 ^ rs2) --
    *resData++ = hw_ell(0u, 0u)
              - sw_sparkle_ell(0, 0);
    *resData++ = hw_ell(0xFFFFFFFFu, 0u)
              - sw_sparkle_ell(0xFFFFFFFF, 0);
    *resData++ = hw_ell(0x12345678u, 0x9ABCDEF0u)
              - sw_sparkle_ell(0x12345678, 0x9ABCDEF0);
    *resData++ = hw_ell(0xDEADBEEFu, 0xCAFEBABEu)
              - sw_sparkle_ell(0xDEADBEEF, 0xCAFEBABE);
    // ell(x, x) = ELL(0) = 0
    *resData++ = hw_ell(0x42424242u, 0x42424242u)
              - sw_sparkle_ell(0x42424242, 0x42424242);

    // -- sparkle_rcon: rd = rs1 ^ RCON[imm] --
    *resData++ = hw_rcon(0u, 0) - sw_rcon(0, 0);
    *resData++ = hw_rcon(0u, 1) - sw_rcon(0, 1);
    *resData++ = hw_rcon(0u, 2) - sw_rcon(0, 2);
    *resData++ = hw_rcon(0u, 3) - sw_rcon(0, 3);
    *resData++ = hw_rcon(0u, 4) - sw_rcon(0, 4);
    *resData++ = hw_rcon(0u, 5) - sw_rcon(0, 5);
    *resData++ = hw_rcon(0u, 6) - sw_rcon(0, 6);
    *resData++ = hw_rcon(0u, 7) - sw_rcon(0, 7);
    // rcon with non-zero input
    *resData++ = hw_rcon(0xFFFFFFFFu, 0) - sw_rcon(0xFFFFFFFF, 0);
    // rs1 == RCON[0] → result should be 0
    *resData++ = hw_rcon(0xB7E15162u, 0) - sw_rcon(0xB7E15162, 0);

    // -- sparkle_whole_enci_x / _y: full ARX-box round --
    sw_whole_enc(0, 0, 0, sw_x, sw_y);
    *resData++ = hw_enci_x(0u, 0u, 0) - sw_x;
    *resData++ = hw_enci_y(0u, 0u, 0) - sw_y;

    sw_whole_enc(0x12345678, 0x9ABCDEF0, 0, sw_x, sw_y);
    *resData++ = hw_enci_x(0x12345678u, 0x9ABCDEF0u, 0) - sw_x;
    *resData++ = hw_enci_y(0x12345678u, 0x9ABCDEF0u, 0) - sw_y;

    sw_whole_enc(0xDEADBEEF, 0xCAFEBABE, 3, sw_x, sw_y);
    *resData++ = hw_enci_x(0xDEADBEEFu, 0xCAFEBABEu, 3) - sw_x;
    *resData++ = hw_enci_y(0xDEADBEEFu, 0xCAFEBABEu, 3) - sw_y;

    sw_whole_enc(0xFFFFFFFF, 0x00000001, 7, sw_x, sw_y);
    *resData++ = hw_enci_x(0xFFFFFFFFu, 0x00000001u, 7) - sw_x;
    *resData++ = hw_enci_y(0xFFFFFFFFu, 0x00000001u, 7) - sw_y;

    // -- Chaining: data-dependent sequences --
    // ell → rcon → whole_enc
    uint32_t e = hw_ell(0xAAAAAAAAu, 0x55555555u);
    *resData++ = e - sw_sparkle_ell(0xAAAAAAAA, 0x55555555);

    uint32_t r = hw_rcon(e, 2);
    *resData++ = r - sw_rcon(sw_sparkle_ell(0xAAAAAAAA, 0x55555555), 2);

    // whole_enc x,y → ell
    uint32_t ex = hw_enci_x(0x11111111u, 0x22222222u, 1);
    uint32_t ey = hw_enci_y(0x11111111u, 0x22222222u, 1);
    sw_whole_enc(0x11111111, 0x22222222, 1, sw_x, sw_y);
    *resData++ = ex - sw_x;
    *resData++ = ey - sw_y;
    *resData++ = hw_ell(ex, ey) - sw_sparkle_ell(sw_x, sw_y);

    return 0;
}
