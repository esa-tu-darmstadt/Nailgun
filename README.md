# NailGun - Custom ISAX Integration Flow

NailGun is intended as a wrapper for configuring and executing our ISAX integration flow (CoreDSL &rarr; Treenail &rarr; Longnail &rarr; SCAIE-V &rarr; extended RISC-V core &rarr; cocotb simulation &rarr; LibreLane).

NailGun is not intended to be used standalone but rather as part of the [integration repository](https://gitlab.esa.informatik.tu-darmstadt.de/scale4edge/isax-tools-integration).

## Plugins

Nailgun provides very rudimentary plugin support.
LibreLane was integrated as synthesis plugin and can be used as an example to develop further plugins.
