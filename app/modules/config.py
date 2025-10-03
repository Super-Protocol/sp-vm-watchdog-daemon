import logging
import json
import os
from collections import Counter
from pathlib import Path

from pydantic import model_validator, BaseModel, Field

from .image_manager import image_manager
from .models import detected_cpu_type, VmQemuConfigMode
from . import utils

__logger__ = logging.getLogger(__name__)


class ProviderConfig(BaseModel):
    test: str


class VmRunConfig(BaseModel):
    debug: bool = False
    build_dir: str | None = None  # model_validator
    vm_build: str | None = None  # model_validator
    argo_branch: str = "main"
    argo_sp_env: str = "main"
    provider_config: ProviderConfig

    @model_validator(mode="after")
    def check_mutually_exclusive(self):
        if self.build_dir and self.vm_build:
            raise ValueError("`build_dir` and `vm_build` are mutually exclusive")
        return self

    @model_validator(mode="after")
    def set_latest_vm_build_if_unset(self):
        if self.build_dir:
            self.vm_build = "build-local"
        elif self.vm_build in [None, "auto"]:
            self.vm_build = image_manager.get_latest_github_release()
        return self


class VmQemuConfig(BaseModel):
    qemu_path: Path | None = None
    mode: VmQemuConfigMode = VmQemuConfigMode.AUTO
    cores: int = Field(..., gt=0)
    mem_gb: int = Field(..., gt=8)
    state_disk_size_gb: int = Field(..., gt=400)
    gpu: str = "all"  # model_validator
    cache_dir: str = None
    mac_address: str = "52:54:00:12:34:56"  # model_validator
    ip_address: str = "0.0.0.0"  # model_validator
    ssh_port: int = 2222
    http_port: int = 0
    https_port: int = 0
    guest_cid: int | None = None

    @model_validator(mode="after")
    def set_qemu_path(self):
        if self.qemu_path is None:
            self.qemu_path = utils.found_system_qemu
        else:  # deserializing str from json conf to Path
            self.qemu_path = Path(self.qemu_path)
            if (not self.qemu_path.is_file()) or (not os.access(self.qemu_path, os.X_OK)):
                raise Exception(f'directly specified qemu path: `{self.qemu_path}` is absent or not executable')
        return self

    @model_validator(mode="after")
    def set_vm_mode(self):
        if self.mode == VmQemuConfigMode.AUTO:
            self.mode = detected_cpu_type
        return self


class VmConfig(BaseModel):
    name: str
    enabled: bool = True
    run_configuration: VmRunConfig
    qemu_configuration: VmQemuConfig

    @classmethod
    def load(cls, filename: str) -> "VmConfig":
        filepath = Path(filename)
        data = filepath.read_text(encoding="utf-8")
        return cls.model_validate_json(data)

    def dump(self) -> str:
        return self.model_dump_json(indent=2)


class TextConfigVmConfig(BaseModel):
    configs_dir: str | None = None
    authorized_keys_file: str | None = None

    @model_validator(mode="after")
    def check_empty_and_set_defaults(self):
        if self.configs_dir is None:
            self.configs_dir = "/var/lib/sp/watchdog/vms"
            __logger__.warning(f"using default vms config dir value `{self.configs_dir}`")
        if len(self.configs_dir) < 1:
            raise Exception(f"wrong vms config dir: `{self.configs_dir}`")

        return self

    @model_validator(mode="after")
    def check_configs_dir_readable(self):
        configs_dir_path = Path(self.configs_dir)
        if not configs_dir_path.is_dir():
            __logger__.info(f"creating vms config dir `{configs_dir_path}`")
            try:
                configs_dir_path.mkdir(parents=True)
            except Exception as e:
                raise Exception(f"failed to create vms config dir: `{configs_dir_path}`, reason: {e}")

        if not os.access(configs_dir_path, os.R_OK):
            raise Exception(f"vms config dir isn't readable: `{configs_dir_path}`")
        return self


class TextConfig(BaseModel):
    vm_config: TextConfigVmConfig = Field(default_factory=TextConfigVmConfig)

    @classmethod
    def load_or_default(cls, filename: str) -> "TextConfig":
        filepath = Path(filename)
        filepath.parent.mkdir(exist_ok=True)

        # creating config, if not exists
        if not filepath.exists():
            c = cls()
            try:
                __logger__.info(f"saving default config to `{filepath}`")
                filepath.touch()
                filepath.write_text(c.dump())
            except Exception as e:
                __logger__.error(f"failed to save default config, reason: {e}")
            finally:
                return c

        data = filepath.read_text(encoding="utf-8")
        return cls.model_validate_json(data)

    def dump(self) -> str:
        return self.model_dump_json(indent=2)


class AppConfig(BaseModel):
    vm_configs: list[VmConfig] = Field(default_factory=list)

    text_config: TextConfig

    @classmethod
    def load(cls, filename: str) -> "AppConfig":
        text_config = TextConfig.load_or_default(filename)

        vm_configs = [VmConfig.load(f) for f in Path(text_config.vm_config.configs_dir).glob("*.json")]
        [print(f.dump()) for f in vm_configs]

        return cls(text_config=text_config, vm_configs=vm_configs)

    @model_validator(mode="after")
    def set_guest_cid(self):
        guest_cid = 3
        aquired_guest_cids = [
            vm.qemu_configuration.guest_cid for vm in self.vm_configs if vm.qemu_configuration.guest_cid is not None
        ]
        for vm in self.vm_configs:
            if vm.qemu_configuration.guest_cid is None:
                while guest_cid in aquired_guest_cids:
                    guest_cid += 1
                vm.qemu_configuration.guest_cid = guest_cid
                guest_cid += 1
        return self

    @model_validator(mode="after")
    def check_unique_fields(self):
        utils.assert_unique(self.vm_configs, "name", "name")
        utils.assert_unique(
            self.vm_configs, "qemu_configuration.ssh_port", "name", lambda x: x.run_configuration.debug == True
        )
        utils.assert_unique(
            self.vm_configs,
            "qemu_configuration.guest_cid",
            "name",
            lambda x: x.qemu_configuration.mode == VmQemuConfigMode.TDX,
        )
        return self
