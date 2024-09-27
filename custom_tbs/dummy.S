.section ".text.init"
.globl _start

_start:
    #ifdef ASM_PERCOREENTRY
    .include ASM_PERCOREENTRY
    #endif

# Completion interrupt.
# NOTE: For cores that can write memory out of order, a write fence may be required here.
	la s0, _ctrlmem
	li t0, 1
	sw t0, 0(s0)

	finloop:
	j finloop
