VERSION ?= 0.0.0

SHELL := /bin/bash

OUTPUT=build
SOURCE=app
MISC=misc

ARGS :=

APP_NAME=sp-vm-watchdog-daemon_$(VERSION)-1_amd64
SOURCES=$(shell find $(SOURCE) -type f)
MISC_FILES=$(shell find $(MISC) -type f)
VENV_DIR=$(OUTPUT)/$(APP_NAME)/usr/bin/sp-vm-watchdog-daemon
VENV_FILE=$(VENV_DIR)/bin/activate

PROTO_DIR=$(SOURCE)/proto
PROTO_GEN_DIR=$(SOURCE)/modules/proto
PROTO_SRC=$(PROTO_DIR)/sp_vm_downloader.proto
PROTO_DST=$(PROTO_GEN_DIR)/sp_vm_downloader_pb2.py \
		  $(PROTO_GEN_DIR)/sp_vm_downloader_pb2_grpc.py

all: $(OUTPUT)/$(APP_NAME).deb

$(VENV_FILE): $(SOURCE)/requirements.txt $(MISC_FILES) Makefile
	@echo -e "\tVENV\t$(VENV_DIR)"
	@mkdir -p $(VENV_DIR)
	@python3 -m venv $(VENV_DIR)
	@source $@ && \
		python3 -m pip install -r \
			$(SOURCE)/requirements.txt && \
		python3 -m pip install -r \
			$(SOURCE)/lint_requirements.txt

$(PROTO_DST): $(PROTO_SRC) $(VENV_FILE)
	@echo -e "\tPROTO\t$<"
	@mkdir -p $(PROTO_GEN_DIR)
	@touch $(PROTO_GEN_DIR)/__init__.py
	@source $(VENV_FILE) && \
		python3 -m grpc_tools.protoc \
		-I $(PROTO_DIR) \
		--python_out=$(PROTO_GEN_DIR) \
		--grpc_python_out=$(PROTO_GEN_DIR) \
		$<
	@python3 misc/scripts/fix_proto_imports.py $(PROTO_GEN_DIR)

.PHONY: run
run: $(PROTO_DST)
	@source $(VENV_FILE) && \
		python3 $(SOURCE)/main.py $(ARGS)


$(OUTPUT)/$(APP_NAME).deb: $(SOURCES) $(PROTO_DST)
	mkdir -p $(OUTPUT)/$(APP_NAME)/DEBIAN
	mkdir -p $(OUTPUT)/$(APP_NAME)/usr/bin
	mkdir -p $(OUTPUT)/$(APP_NAME)/etc/systemd/system/
	mkdir -p $(OUTPUT)/$(APP_NAME)/usr/bin
	mkdir -p $(OUTPUT)/$(APP_NAME)/usr/bin/sp-vm-watchdog-daemon/app
	cp -Lr $(SOURCE) $(OUTPUT)/$(APP_NAME)/usr/bin/sp-vm-watchdog-daemon/
	cp $(MISC)/sp-vm-watchdog-daemon.service $(OUTPUT)/$(APP_NAME)/etc/systemd/system/sp-vm-watchdog-daemon.service
	VERSION="${VERSION}" envsubst '$$VERSION' < $(MISC)/control > $(OUTPUT)/$(APP_NAME)/DEBIAN/control
	cp $(MISC)/postinst $(OUTPUT)/$(APP_NAME)/DEBIAN/
	cp $(MISC)/prerm $(OUTPUT)/$(APP_NAME)/DEBIAN/
	cp $(MISC)/postrm $(OUTPUT)/$(APP_NAME)/DEBIAN/
	dpkg-deb --build --root-owner-group $(OUTPUT)/$(APP_NAME)

.PHONY: format
format: $(VENV_FILE)
	@source $(VENV_FILE) && \
		python3 -m isort --profile black --length-sort --reverse-sort \
			--multi-line 3 --skip-glob '*_pb2.py' --skip-glob '*_pb2_grpc.py' .
	@source $(VENV_FILE) && \
		python3 -m black --skip-string-normalization \
			--line-length=120 --extend-exclude '.*_pb2(_grpc)?\.py' .

.PHONY: lint
lint: $(VENV_FILE) $(PROTO_DST)
	@source $(VENV_FILE) && \
		python3 -m isort --profile black --length-sort --reverse-sort \
			--multi-line 3 --skip-glob '*_pb2.py' --skip-glob '*_pb2_grpc.py' --check --diff .
	@source $(VENV_FILE) && \
		python3 -m black --skip-string-normalization \
			--line-length=120 --extend-exclude '.*_pb2(_grpc)?\.py' --check --diff .
	@source $(VENV_FILE) && \
		python3 -m mypy $(SOURCE)/main.py

.PHONY: clean
clean:
	rm -rf $(OUTPUT)
