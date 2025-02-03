ENTRY(_start)
MEMORY
{
    imem (rxa) : ORIGIN = 0x00000000, LENGTH = 1M
    dmem (rwa) : ORIGIN = 0x00100000, LENGTH = 1M
    ctrl (w) : ORIGIN = 0x00200000, LENGTH = 1M
}
SECTIONS
{
    __stack_size = 0x1000;
    __indata_size = 0x1000;
    __resdata_size = 0x1000;

    . = ORIGIN(imem);

    .text.init : {
            * (.text.init);
    } > imem
    .text.irq : ALIGN(0x100) {
          * (.text.freertos_risc_v_trap_handler);
          * (.text.trap_handler)
    } > imem
    .text : {
          * (.text);
    } > imem
    .interp : { *(.interp) } > imem
    .eh_frame : {
        *(.eh_frame)
    } > imem

    . = ORIGIN(dmem);
    PROVIDE( _test_indata = ORIGIN(dmem) );
    PROVIDE( _test_resdata = ORIGIN(dmem) + __indata_size );
    .srodata : {
          * (.srodata);
    } > dmem
    .rodata : {
          * (.rodata);
    } > dmem
    .sdata : {
          * (.sdata*);
    } > dmem
    .sbss : {
         * (.sbss*);
    } > dmem
    .data : {
        * (.data);
    } > dmem
    .bss : {
         * (.bss);
    } > dmem
    PROVIDE ( _heap_start = .);

    .stack ORIGIN(dmem) + LENGTH(dmem) - __stack_size :
    {
        . = ORIGIN(dmem) + LENGTH(dmem);
        PROVIDE( _sp = . );
        PROVIDE (_stack_top = .);
    } > dmem

    PROVIDE( _ctrlmem = ORIGIN(ctrl) );
}
