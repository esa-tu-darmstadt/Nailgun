.section ".text.init"
.globl _start

_start:
    #ifdef ASM_PERCOREENTRY
    .include ASM_PERCOREENTRY
    #endif
    la a1, test_data
    la a2, _test_resdata

    jal ra, load_operands
    complexadd t0, t0, t1
    jal ra, store_result

    jal ra, load_4_operands
    complexadd t0, t0, t1
    complexadd t1, t2, t3
    jal ra, store_2_result

    jal ra, load_4_operands
    complexadd t0, t2, t3
    complexadd t1, t0, t1
    jal ra, store_2_result

	# This fails currently without an ISAX controller
    jal ra, load_4_operands
    complexmul t0, t0, t1
    complexadd t1, t2, t3
    jal ra, store_2_result

# Completion interrupt.
# NOTE: For cores that can write memory out of order, a write fence may be required here.
    la s0, _ctrlmem
    li t0, 1
    sw t0, 0(s0)

    finloop:
    j finloop


# Available operations:
# COMPLEX_ADD
# COMPLEX_MUL

load_operands:
    lw t0, 0(a1)
    lw t1, 4(a1)
    slli t0, t0, 16
    slli t1, t1, 16
    srli t1, t1, 16
    or t0, t0, t1
    lw t1, 8(a1)
    lw t2, 12(a1)
    slli t1, t1, 16
    slli t2, t2, 16
    srli t2, t2, 16
    or t1, t1, t2
    addi a1, a1, 16
    ret

load_4_operands:
	mv t6, ra
    jal ra, load_operands
    mv t4, t0
    mv t5, t1
    jal ra, load_operands
    mv t2, t0
    mv t3, t1
    mv t0, t4
    mv t1, t5
	mv ra, t6
    ret

store_result:
    sw t0, 0(a2)
    addi a2, a2, 4
    ret

store_2_result:
    sw t0, 0(a2)
    sw t1, 4(a2)
    addi a2, a2, 8
    ret

.data
test_data:
# complexadd
# operand 1:
.word -3
.word 2
# operand 2:
.word 45
.word 40
# complexadd & complexadd
# operand 1:
.word -42
.word -42
# operand 2:
.word 21
.word 42
# operand 3:
.word -5
.word -128
# operand 4:
.word 32767
.word -256
# complexadd & complexadd register conflict
# operand 3: dont care
.word -1
.word -1
# operand 4:
.word 21
.word 42
# operand 1:
.word 10
.word -128
# operand 2:
.word 11
.word 128
# complexmul & complexadd
# operand 1:
.word -42
.word -42
# operand 2:
.word 21
.word -42
# operand 3:
.word -32768
.word 0
# operand 4:
.word 32767
.word -256

