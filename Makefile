all: menuconfig

gen_config: clean_config
	python3 gen_config.py

menuconfig: gen_config
	python3 -m menuconfig

build: gen_config .config
	python3 dispatch.py

clean_config:
	rm -rf build/ISAX

clean:
	rm -rf build

mrproper: clean
	rm -rf output*

.PHONY : build menuconfig gen_config clean clean_config mrproper
