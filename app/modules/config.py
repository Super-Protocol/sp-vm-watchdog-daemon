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
    execution_controller_tee_prov_configmap: str
    sp_pki_challenge_secret: str | None = None

    @model_validator(mode="after")
    def check_execution_controller_tee_prov_configmap(self):
        configmap_path = Path(self.execution_controller_tee_prov_configmap)
        if not os.access(configmap_path, os.R_OK):
            raise Exception(f"execution_controller_tee_prov_configmap isn't readable: `{configmap_path}`")
        return self

    @model_validator(mode="after")
    def check_sp_pki_challenge_secret(self):
        if self.sp_pki_challenge_secret is not None:
            secret_path = Path(self.sp_pki_challenge_secret)
            if not os.access(secret_path, os.R_OK):
                raise Exception(f"sp_pki_challenge_secret isn't readable: `{secret_path}`")
        return self


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
    gpu: str = "all"
    cache_dir: str | None = None
    mac_address: str = "52:54:00:12:34:56"
    ip_address: str = "0.0.0.0"
    ssh_port: int = 2222
    http_port: int | None = None
    https_port: int | None = None
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

    # need to be here cause we'r not know the vm name being level down
    # maybe it needs to be a more levels upper to prevent `'/var/lib/sp/watchdog` hardcode
    @model_validator(mode="after")
    def set_cache_dir(self):
        if self.qemu_configuration.cache_dir is None:
            vm_cache_dir = Path('/var/lib/sp/watchdog/cache') / Path(self.name)
            vm_cache_dir.mkdir(exist_ok=True, parents=True)
            self.qemu_configuration.cache_dir = str(vm_cache_dir)
        return self


class TextConfigVmConfig(BaseModel):
    configs_dir: str = "/etc/sp/watchdog/vms"
    authorized_keys_file: str | None = None

    @model_validator(mode="after")
    def check_configs_dir_readable(self):
        configs_dir_path = Path(self.configs_dir)
        configs_dir_path.mkdir(parents=True, exist_ok=True)
        if not os.access(configs_dir_path, os.R_OK):
            raise Exception(f"vms config dir isn't readable: `{configs_dir_path}`")
        return self

    @model_validator(mode="after")
    def check_authorized_keys_file_readable(self):
        authorized_keys_file_path = Path(self.authorized_keys_file)
        if not authorized_keys_file_path.is_file() or not os.access(authorized_keys_file_path, os.R_OK):
            raise Exception(f"authorized_keys_file isn't readable: `{authorized_keys_file_path}`")
        return self


class TextConfig(BaseModel):
    vm_config: TextConfigVmConfig = Field(default_factory=TextConfigVmConfig)

    @classmethod
    def load_or_default(cls, filename: str) -> "TextConfig":
        filepath = Path(filename)
        filepath.parent.mkdir(exist_ok=True, parents=True)

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

        vm_configs = [
            VmConfig.load(f)
            for f in sorted(Path(text_config.vm_config.configs_dir).glob("*.json"), key=lambda p: p.name)
        ]
        # [print(f.dump()) for f in vm_configs]

        return cls(text_config=text_config, vm_configs=vm_configs)

    @model_validator(mode="after")
    def remove_disabled_vms(self):
        vm_configs = [vm for vm in self.vm_configs if vm.enabled == True]
        self.vm_configs = vm_configs
        return self

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
        utils.assert_unique_pair(
            self.vm_configs,
            "qemu_configuration.http_port",
            "qemu_configuration.ip_address",
            "name",
            lambda x: x.qemu_configuration.http_port is not None,
        )
        utils.assert_unique_pair(
            self.vm_configs,
            "qemu_configuration.https_port",
            "qemu_configuration.ip_address",
            "name",
            lambda x: x.qemu_configuration.https_port is not None,
        )
        # TODO: check port in use (don't know in use by already running VM or by foreign process)
        return self
