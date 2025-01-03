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

    . = ORIGIN(imem) + 0x1000;

    .text.init ORIGIN(imem) + 0x1000 : {
            * (.text.init);
    } > imem
    .text : {
          * (.text);
    } > imem
    .interp : { *(.interp) } > imem
    .eh_frame : {
        *(.eh_frame)
    } > imem

    . = ORIGIN(dmem);
    .input_data : {
        PROVIDE( _test_indata = ORIGIN(dmem) );
          * (.input_data);
    } > dmem

    PROVIDE( _test_resdata = ORIGIN(dmem) + __indata_size );
    .data : {
        * (.data);
    } > dmem
    .srodata : {
          * (.srodata);
    } > dmem
    .rodata : {
          * (.rodata);
    } > dmem
    .bss : {
         * (.bss);
    } > dmem

    .stack ORIGIN(dmem) + LENGTH(dmem) - __stack_size :
    {
        . = ORIGIN(dmem) + LENGTH(dmem);
        PROVIDE( _sp = . );
    } > dmem

    PROVIDE( _ctrlmem = ORIGIN(ctrl) );
}
