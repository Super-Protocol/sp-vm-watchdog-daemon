VERSION ?= 0.0.0

SHELL := /bin/bash

OUTPUT=build
SOURCE=app
MISC=misc

ARGS :=

APP_NAME=sp-vm-watchdog-daemon_$(VERSION)-1_amd64
SOURCES=$(shell find $(SOURCE) -type f)
MISC_FILES=$(shell find $(MISC) -type f)

all: $(OUTPUT)/$(APP_NAME).deb

$(OUTPUT)/venv/bin/activate: $(SOURCE)/requirements.txt $(MISC_FILES) Makefile
	@echo -e "\tVENV\t$(OUTPUT)/venv"
	@mkdir -p $(OUTPUT)/venv
	@python3 -m venv $(OUTPUT)/venv
	@source $(OUTPUT)/venv/bin/activate \
		&& python3 -m pip install -r \
		$(SOURCE)/requirements.txt

.PHONY: run
run: $(OUTPUT)/venv/bin/activate
	@source $(OUTPUT)/venv/bin/activate \
		&& python3 $(SOURCE)/main.py $(ARGS)


$(OUTPUT)/$(APP_NAME).deb: $(SOURCES) $(MISC_FILES) Makefile
	mkdir -p $(OUTPUT)/$(APP_NAME)/DEBIAN
	mkdir -p $(OUTPUT)/$(APP_NAME)/usr/bin
	mkdir -p $(OUTPUT)/$(APP_NAME)/etc/systemd/system/
	python3 -m venv $(OUTPUT)/$(APP_NAME)/usr/bin/sp-vm-watchdog-daemon
	mkdir -p $(OUTPUT)/$(APP_NAME)/usr/bin
	cp -Lr $(SOURCE) $(OUTPUT)/$(APP_NAME)/usr/bin/sp-vm-watchdog-daemon/app
	cp $(MISC)/sp-vm-watchdog-daemon.service $(OUTPUT)/$(APP_NAME)/etc/systemd/system/sp-vm-watchdog-daemon.service
	source $(OUTPUT)/$(APP_NAME)/usr/bin/sp-vm-watchdog-daemon/bin/activate \
		&& python3 -m pip install -r \
		$(OUTPUT)/$(APP_NAME)/usr/bin/sp-vm-watchdog-daemon/app/requirements.txt
	envsubst < $(MISC)/control > $(OUTPUT)/$(APP_NAME)/DEBIAN/control
	cp $(MISC)/postinst $(OUTPUT)/$(APP_NAME)/DEBIAN/
	cp $(MISC)/prerm $(OUTPUT)/$(APP_NAME)/DEBIAN/
	dpkg-deb --build --root-owner-group $(OUTPUT)/$(APP_NAME)

.PHONY: format
format:
	python3 -m isort --profile black --length-sort --reverse-sort  --multi-line 3 .
	python3 -m black --skip-string-normalization --line-length=120 .

.PHONY: lint
lint:
	python3 -m isort --profile black --length-sort --reverse-sort  --multi-line 3 --check --diff .
	python3 -m black --skip-string-normalization --line-length=120 --check --diff .

.PHONY: clean
clean:
	rm -rf $(OUTPUT)
