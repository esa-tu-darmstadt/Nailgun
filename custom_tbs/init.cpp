#if __has_builtin(__builtin_riscv_merged_initrf42)
#define ASM_PREFIX "MERGED"
#else
#define ASM_PREFIX "init"
#endif

int main() {
  // INIT_RF_42 sets all registers X[1..31] to 42.
  // This destroys sp, ra, and all other registers, so we must
  // save/restore state and capture results in a single asm block.
  asm volatile(
      // Save sp and ra to fixed memory (before _test_resdata)
      "la t0, _ctx_state_start\n"
      "sw sp, 4(t0)\n"
      "sw ra, 8(t0)\n"
      // Execute init.initrf42
      ASM_PREFIX ".initrf42\n"
      // All regs X[1..31] are now 42.
      // Accumulate all of them into x31
      "add x31, x31, x1\n"
      "add x31, x31, x2\n"
      "add x31, x31, x3\n"
      "add x31, x31, x4\n"
      "add x31, x31, x5\n"
      "add x31, x31, x6\n"
      "add x31, x31, x7\n"
      "add x31, x31, x8\n"
      "add x31, x31, x9\n"
      "add x31, x31, x10\n"
      "add x31, x31, x11\n"
      "add x31, x31, x12\n"
      "add x31, x31, x13\n"
      "add x31, x31, x14\n"
      "add x31, x31, x15\n"
      "add x31, x31, x16\n"
      "add x31, x31, x17\n"
      "add x31, x31, x18\n"
      "add x31, x31, x19\n"
      "add x31, x31, x20\n"
      "add x31, x31, x21\n"
      "add x31, x31, x22\n"
      "add x31, x31, x23\n"
      "add x31, x31, x24\n"
      "add x31, x31, x25\n"
      "add x31, x31, x26\n"
      "add x31, x31, x27\n"
      "add x31, x31, x28\n"
      "add x31, x31, x29\n"
      "add x31, x31, x30\n"
      // Reload result pointer
      "la x30, _test_resdata\n"
      // Store accumulated value as proof that all registers have been 42
      "sw x31, 0(x30)\n"
      // Restore sp and ra
      "la x30, _ctx_state_start\n"
      "lw sp, 4(x30)\n"
      "lw ra, 8(x30)\n"
      ::: "memory", "ra", "gp", "tp",
          "t0", "t1", "t2", "t3", "t4", "t5", "t6",
          "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7",
          "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
          "s8", "s9", "s10", "s11");
  return 0;
}
