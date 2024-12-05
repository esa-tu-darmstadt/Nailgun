.section ".text.init"
.globl _start

_start:
    #ifdef ASM_PERCOREENTRY
    .include ASM_PERCOREENTRY
    #endif
    la a1, test_data
    la a2, _test_resdata

# L1 norm
    jal ra, load_vecs
    l1_norm_vec t0, x0
    sw t0, 0(a2)
    l1_norm_vec t0, x1
    sw t0, 4(a2)
    l1_norm_vec t0, x2
    sw t0, 8(a2)
    l1_norm_vec t0, x3
    sw t0, 12(a2)
    addi a2, a2, 16

# Dot product
    # a1=resdata+0x30
    # a2=resdata+0x10
    jal ra, load_vecs
    vec_dot t0, x0, x0
    sw t0, 0(a2)
    vec_dot t0, x0, x1
    sw t0, 4(a2)
    vec_dot t0, x0, x2
    sw t0, 8(a2)
    vec_dot t0, x0, x3
    sw t0, 12(a2)
    vec_dot t0, x1, x1
    sw t0, 16(a2)
    vec_dot t0, x1, x2
    sw t0, 20(a2)
    vec_dot t0, x1, x3
    sw t0, 24(a2)
    vec_dot t0, x2, x2
    sw t0, 28(a2)
    vec_dot t0, x2, x3
    sw t0, 32(a2)
    vec_dot t0, x3, x3
    sw t0, 36(a2)
    addi a2, a2, 40

# Vector addition
    # a1=resdata+0x60
    # a2=resdata+0x38

    jal ra, load_vecs
    vec_add x3, x0, x3
    vec_add x2, x0, x2
    vec_add x1, x0, x1
    vec_add x0, x0, x0
    jal ra, save_vecs

# Vector scaling
    # a1=resdata+0x90
    # a2=resdata+0x68

    jal ra, load_vecs
    li t0, 42
    vec_scale x0, x0, t0
    vec_scale x1, x1, t0
    vec_scale x2, x2, t0
    vec_scale x3, x3, t0
    jal ra, save_vecs

# Vector element-wise multiply
    # a1=resdata+0xc0
    # a2=resdata+0x98

    jal ra, load_vecs
    vec_mul x0, x0, x0
    vec_mul x1, x1, x1
    vec_mul x2, x2, x2
    vec_mul x3, x3, x3
    jal ra, save_vecs

# Matrix Vector multiply + translation
    # a1=resdata+0xf0
    # a2=resdata+0xc8

    jal ra, load_vecs
    la t1, tranlation_z
    set_addr t1
    li t2, 1
    li a0, 3
    mat_mul_trans x3, t2, t2
    jal ra, save_vec
    # a2=resdata+0xd4
    set_addr t1
    mat_mul_trans x3, t2, t2
    jal ra, save_vec
    # a2=resdata+0xe0
    set_addr t1
    mat_mul_trans x3, t2, t2
    jal ra, save_vec
    # a2=resdata+0xec
    set_addr t1
    mat_mul_trans x3, t2, t2
    jal ra, save_vec

# Completion interrupt.
# NOTE: For cores that can write memory out of order, a write fence may be required here.
	la s0, _ctrlmem
	li t0, 1
	sw t0, 0(s0)

	finloop:
	j finloop

# Available custom instructions:
# set_addr rs1
# set_inc rs1
# export_vec_entry rd, rs1 (vec sel), rs2 (enableMemExport, memEntrySel, regEntrySel)
# import_vec

# l1_norm_reg
# l1_norm_vec
# vec_dot
# vec_add
# vec_scale
# vec_mul
# mat_mul_trans

# Arguments: a2 = result addr
#            a0 = vec idx
save_vec:
    li t0, 4
    set_inc t0
    set_addr a2
    # 0b10000 = x16 get MEM[addr] = vec[x]
    export_vec_entry t0, a0, x16
    # 0b10100 = x20 get MEM[addr + 4] = vec[y]
    export_vec_entry t0, a0, x20
    # 0b11000 = x24 get MEM[addr + 8] = vec[z]
    export_vec_entry t0, a0, x24
    addi a2, a2, 12
    ret

# Arguments: a2 = result addr
save_vecs:
    li t0, 4
    set_inc t0
    set_addr a2
    li a0, 0
    # export_vec_entry rd, rs1 (vec sel), rs2 (enableMemExport, memEntrySel, regEntrySel)
    # 0b10000 = x16 get MEM[addr] = vec0[x]
    export_vec_entry t0, a0, x16
    # 0b10100 = x20 get MEM[addr + 4] = vec0[y]
    export_vec_entry t0, a0, x20
    # 0b11000 = x24 get MEM[addr + 8] = vec0[z]
    export_vec_entry t0, a0, x24
    li a0, 1
    export_vec_entry t0, a0, x16
    export_vec_entry t0, a0, x20
    export_vec_entry t0, a0, x24
    li a0, 2
    export_vec_entry t0, a0, x16
    export_vec_entry t0, a0, x20
    export_vec_entry t0, a0, x24
    li a0, 3
    export_vec_entry t0, a0, x16
    export_vec_entry t0, a0, x20
    export_vec_entry t0, a0, x24
    addi a2, a2, 48
    ret

# Arguments: a1 = vec addr
load_vecs:
    li t0, 12
    set_inc t0
    addi a1, a1, 8
    set_addr a1

    lw t0, -8(a1)
    lw t1, -4(a1)
    import_vec x0, t0, t1
    lw t0, 4(a1)
    lw t1, 8(a1)
    import_vec x1, t0, t1
    lw t0, 16(a1)
    lw t1, 20(a1)
    import_vec x2, t0, t1
    lw t0, 28(a1)
    lw t1, 32(a1)
    import_vec x3, t0, t1
    addi a1, a1, 40
    ret

.data
tranlation_z:
.word 1
test_data:
# L1 norm test vectors
# vec0:
.word -1
.word -2
.word -3
# vec1:
.word 1
.word 2
.word 3
# vec2:
.word 4
.word -5
.word 6
# vec3:
.word -7
.word 8
.word -9
# Dot product test vectors
# vec0:
.word 1
.word 0
.word 0
# vec1:
.word 1
.word 1
.word 1
# vec2:
.word 2
.word -2
.word 2
# vec3:
.word -1
.word 0
.word 1
# Vector addition test vectors
# vec0:
.word -1
.word -2
.word -3
# vec1:
.word 1
.word 0
.word 1
# vec2:
.word 1
.word 2
.word 3
# vec3:
.word 1338
.word 44
.word 65539
# Vector scaling test vectors
# vec0:
.word -1
.word -2
.word -3
# vec1:
.word 1
.word 42
.word -1
# vec2:
.word 10
.word 20
.word 300
# vec3:
.word 1001
.word 10001
.word 1001001
# Vector element-wise multiply test vectors
# vec0:
.word -1
.word -2
.word -3
# vec1:
.word 1
.word 42
.word -10
# vec2:
.word 10
.word 20
.word 300
# vec3:
.word 1001
.word 10001
.word 65536
# Matrix Vector multiply + translation test vectors
# vec0:
.word 2
.word 1
.word 0
# vec1:
.word 5
.word -3
.word 4
# vec2:
.word 8
.word 6
.word -7
# vec3:
.word 3
.word -2
.word 7
