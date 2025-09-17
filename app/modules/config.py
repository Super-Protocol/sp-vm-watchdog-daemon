import logging
import json
import os
from collections import Counter
from pathlib import Path
from enum import Enum

from pydantic import model_validator, BaseModel, Field

from . import utils

__logger__ = logging.getLogger(__name__)


class VmQemuConfigMode(str, Enum):
    AUTO = "auto"
    TDX = "tdx"
    SEV_SNP = "sev-snp"
    UNTRUSTED = "untrusted"


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
        if not self.build_dir and not self.vm_build:
            raise ValueError("`build_dir` or `vm_build` must be set")
        return self


class VmQemuConfig(BaseModel):
    mode: VmQemuConfigMode = VmQemuConfigMode.AUTO
    cores: int = Field(..., gt=0)
    mem_gb: int = Field(..., gt=8)
    state_disk_size_gb: int = Field(..., gt=400)
    gpu: str = "all"  # model_validator
    cache_dir: str
    mac_address: str = "52:54:00:12:34:56"  # model_validator
    ip_address: str = "0.0.0.0"  # model_validator
    ssh_port: int = 2222
    http_port: int = 0
    https_port: int = 0


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
    def check_unique_fields(self):
        utils.assert_unique(self.vm_configs, "name", "name")
        utils.assert_unique(
            self.vm_configs, "qemu_configuration.ssh_port", "name", lambda x: x.run_configuration.debug == True
        )
        return self
