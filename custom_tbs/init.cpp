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
      "la t0, _test_resdata\n"
      "sw sp, -4(t0)\n"
      "sw ra, -8(t0)\n"
      // Execute init.initrf42
      ASM_PREFIX ".initrf42\n"
      // All regs X[1..31] are now 42.
      // Reload result pointer (t0 was clobbered to 42).
      "la t0, _test_resdata\n"
      // Store register values as proof they are 42
      "sw a0, 0(t0)\n"
      "sw a1, 4(t0)\n"
      "sw s0, 8(t0)\n"
      "sw sp, 12(t0)\n"
      "sw ra, 16(t0)\n"
      // Sentinel
      "li t1, -1\n"
      "sw t1, 20(t0)\n"
      // Restore sp and ra
      "lw sp, -4(t0)\n"
      "lw ra, -8(t0)\n"
      ::: "memory", "ra", "gp", "tp",
          "t0", "t1", "t2", "t3", "t4", "t5", "t6",
          "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7",
          "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
          "s8", "s9", "s10", "s11");
  return 0;
}
