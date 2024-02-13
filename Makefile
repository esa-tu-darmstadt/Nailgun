menuconfig:
	python3 -m menuconfig

.PHONY : build
build:
	python3 dispatch.py