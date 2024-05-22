menuconfig:
	python3 -m menuconfig

build:
	python3 dispatch.py

all: menuconfig
.PHONY : build menuconfig
