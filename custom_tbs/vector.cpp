#include "utils/sim.h"

#if __has_builtin(__builtin_riscv_merged_vecsetaddr) ||                        \
    defined(TB_FORCE_USE_MERGED)
#define __builtin_riscv_vecsetaddr __builtin_riscv_merged_vecsetaddr
#define __builtin_riscv_vecsetinc __builtin_riscv_merged_vecsetinc
#define __builtin_riscv_importvec __builtin_riscv_merged_importvec
#define __builtin_riscv_exportvecentry __builtin_riscv_merged_exportvecentry
#define __builtin_riscv_l1normvec __builtin_riscv_merged_l1normvec
#define __builtin_riscv_vecdot __builtin_riscv_merged_vecdot
#define __builtin_riscv_vecadd __builtin_riscv_merged_vecadd
#define __builtin_riscv_vecscale __builtin_riscv_merged_vecscale
#define __builtin_riscv_vecmul __builtin_riscv_merged_vecmul
#define __builtin_riscv_matmultrans __builtin_riscv_merged_matmultrans
#else
#define __builtin_riscv_vecsetaddr __builtin_riscv_vector_vecsetaddr
#define __builtin_riscv_vecsetinc __builtin_riscv_vector_vecsetinc
#define __builtin_riscv_importvec __builtin_riscv_vector_importvec
#define __builtin_riscv_exportvecentry __builtin_riscv_vector_exportvecentry
#define __builtin_riscv_l1normvec __builtin_riscv_vector_l1normvec
#define __builtin_riscv_vecdot __builtin_riscv_vector_vecdot
#define __builtin_riscv_vecadd __builtin_riscv_vector_vecadd
#define __builtin_riscv_vecscale __builtin_riscv_vector_vecscale
#define __builtin_riscv_vecmul __builtin_riscv_vector_vecmul
#define __builtin_riscv_matmultrans __builtin_riscv_vector_matmultrans
#endif

// Builtin signatures (canonical: registers first by LSB, then immediates by
// LSB):
//   void vecsetaddr(int rs1)
//   void vecsetinc(int rs1)
//   void importvec(int rs1, int rs2, int sel)         -- sel: 2-bit imm (vec
//   index) int  exportvecentry(int rs1, int rs2, int memSel) -- rs1: GPR (vec
//   index), rs2/memSel: 2-bit imm int  l1normvec(int rs1) -- rs1: 2-bit imm
//   (vec index) int  vecdot(int rs1, int rs2)                     -- both 2-bit
//   imm (vec indices) void vecadd(int rd, int rs1, int rs2)             -- all
//   2-bit imm (vec indices) void vecscale(int rs2, int rd, int rs1) -- rs2: GPR
//   (scale factor), rd/rs1: 2-bit imm void vecmul(int rd, int rs1, int rs2) --
//   all 2-bit imm (vec indices) void matmultrans(int rs1, int rs2, int resIdx)
//   -- rs1/rs2: GPR, resIdx: 2-bit imm

// Load 4 vectors (12 words) from data into vec0-vec3, advance data pointer.
// importvec: x=GPR[rs1], y=GPR[rs2], z=MEM[ADDR]; ADDR auto-increments by INC.
static void load_vecs(int *&data) {
  __builtin_riscv_vecsetinc(12);
  __builtin_riscv_vecsetaddr((int)&data[2]);
  __builtin_riscv_importvec(data[0], data[1], 0);
  __builtin_riscv_importvec(data[3], data[4], 1);
  __builtin_riscv_importvec(data[6], data[7], 2);
  __builtin_riscv_importvec(data[9], data[10], 3);
  data += 12;
}

// Export all 4 vectors (12 words) to resData via MEM[ADDR], advance resData.
// exportvecentry(vecIdx, rs2=component_for_rd, memSel=component_for_mem)
//   memSel: 0=x, 1=y, 2=z
static void save_vecs(unsigned *&resData) {
  __builtin_riscv_vecsetinc(4);
  __builtin_riscv_vecsetaddr((int)resData);
  for (int i = 0; i < 4; i++) {
    (void)__builtin_riscv_exportvecentry(i, 0, 0);
    (void)__builtin_riscv_exportvecentry(i, 0, 1);
    (void)__builtin_riscv_exportvecentry(i, 0, 2);
  }
  resData += 12;
}

// Export one vector (3 words) to resData via MEM[ADDR], advance resData.
static void save_vec(unsigned *&resData, int vecIdx) {
  __builtin_riscv_vecsetinc(4);
  __builtin_riscv_vecsetaddr((int)resData);
  (void)__builtin_riscv_exportvecentry(vecIdx, 0, 0);
  (void)__builtin_riscv_exportvecentry(vecIdx, 0, 1);
  (void)__builtin_riscv_exportvecentry(vecIdx, 0, 2);
  resData += 3;
}

static int test_data[] = {
    // L1 norm test vectors
    -1, -2, -3, // vec0
    1, 2, 3,    // vec1
    4, -5, 6,   // vec2
    -7, 8, -9,  // vec3
    // Dot product test vectors
    1, 0, 0,  // vec0
    1, 1, 1,  // vec1
    2, -2, 2, // vec2
    -1, 0, 1, // vec3
    // Vector addition test vectors
    -1, -2, -3,      // vec0
    1, 0, 1,         // vec1
    1, 2, 3,         // vec2
    1338, 44, 65539, // vec3
    // Vector scaling test vectors
    -1, -2, -3,           // vec0
    1, 42, -1,            // vec1
    10, 20, 300,          // vec2
    1001, 10001, 1001001, // vec3
    // Vector element-wise multiply test vectors
    -1, -2, -3,         // vec0
    1, 42, -10,         // vec1
    10, 20, 300,        // vec2
    1001, 10001, 65536, // vec3
    // Matrix-vector multiply + translation test vectors
    2, 1, 0,  // vec0
    5, -3, 4, // vec1
    8, 6, -7, // vec2
    3, -2, 7, // vec3
};

static volatile int translation_z = 1;

int main() {
  auto resData = getResultPtr();
  int *data = test_data;

  // L1 norm (4 results)
  load_vecs(data);
  resData[0] = __builtin_riscv_l1normvec(0);
  resData[1] = __builtin_riscv_l1normvec(1);
  resData[2] = __builtin_riscv_l1normvec(2);
  resData[3] = __builtin_riscv_l1normvec(3);
  resData += 4;

  // Dot product (10 results)
  load_vecs(data);
  resData[0] = __builtin_riscv_vecdot(0, 0);
  resData[1] = __builtin_riscv_vecdot(0, 1);
  resData[2] = __builtin_riscv_vecdot(0, 2);
  resData[3] = __builtin_riscv_vecdot(0, 3);
  resData[4] = __builtin_riscv_vecdot(1, 1);
  resData[5] = __builtin_riscv_vecdot(1, 2);
  resData[6] = __builtin_riscv_vecdot(1, 3);
  resData[7] = __builtin_riscv_vecdot(2, 2);
  resData[8] = __builtin_riscv_vecdot(2, 3);
  resData[9] = __builtin_riscv_vecdot(3, 3);
  resData += 10;

  // Vector addition (12 results)
  // vec3=vec0+vec3, vec2=vec0+vec2, vec1=vec0+vec1, vec0=vec0+vec0
  // (vec0 overwritten last so all adds use original vec0)
  load_vecs(data);
  __builtin_riscv_vecadd(3, 0, 3);
  __builtin_riscv_vecadd(2, 0, 2);
  __builtin_riscv_vecadd(1, 0, 1);
  __builtin_riscv_vecadd(0, 0, 0);
  save_vecs(resData);

  // Vector scaling (12 results)
  load_vecs(data);
  __builtin_riscv_vecscale(42, 0, 0);
  __builtin_riscv_vecscale(42, 1, 1);
  __builtin_riscv_vecscale(42, 2, 2);
  __builtin_riscv_vecscale(42, 3, 3);
  save_vecs(resData);

  // Vector element-wise multiply (12 results)
  load_vecs(data);
  __builtin_riscv_vecmul(0, 0, 0);
  __builtin_riscv_vecmul(1, 1, 1);
  __builtin_riscv_vecmul(2, 2, 2);
  __builtin_riscv_vecmul(3, 3, 3);
  save_vecs(resData);

  // Matrix-vector multiply + translation (12 results)
  // matmultrans: vec[resIdx] = M * vec[resIdx] + translation
  //   translation = (GPR[rs1]=1, GPR[rs2]=1, MEM[ADDR]=1)
  // Each iteration overwrites vec3; result fed to next iteration.
  load_vecs(data);
  __builtin_riscv_vecsetaddr((int)&translation_z);
  __builtin_riscv_matmultrans(1, 1, 3);
  save_vec(resData, 3);

  __builtin_riscv_vecsetaddr((int)&translation_z);
  __builtin_riscv_matmultrans(1, 1, 3);
  save_vec(resData, 3);

  __builtin_riscv_vecsetaddr((int)&translation_z);
  __builtin_riscv_matmultrans(1, 1, 3);
  save_vec(resData, 3);

  __builtin_riscv_vecsetaddr((int)&translation_z);
  __builtin_riscv_matmultrans(1, 1, 3);
  save_vec(resData, 3);

  return 0;
}
