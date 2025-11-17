import subprocess
import logging
import json
from pathlib import Path
from hashlib import md5
from typing import Tuple, Dict

from pydantic import model_validator, BaseModel, Field

from .image_manager import image_manager
from .gpu_manager import gpu_manager, Device
from .models import VmQemuConfigMode
from .config import AppConfig, VmConfig
from .utils import detected_cpu_cbitpos, phys_bits, snp_vcpu

__logger__ = logging.getLogger(__name__)


class Qemu(BaseModel):
    app_config: AppConfig
    config: VmConfig
    cmd: list[str] | None = None
    state_disk_path: Path
    provider_config_disk_path: Path
    provider_config_files: Dict[str, str] = Field(default_factory=dict)
    provider_config_files_hash: bytes | None = None
    pci_device_count: int = 0

    @classmethod
    def load_from_config(cls, app_config: AppConfig, config: VmConfig) -> "Qemu":
        provider_config_disk_path = Path(config.qemu_configuration.cache_dir) / Path('provider_config.img')  # type: ignore[arg-type]
        state_disk_path = Path(config.qemu_configuration.cache_dir) / Path('state.qcow2')  # type: ignore[arg-type]

        c = cls(
            app_config=app_config,
            config=config,
            provider_config_disk_path=provider_config_disk_path,
            state_disk_path=state_disk_path,
        )
        c.cmd = c.get_cmdline_from_config()
        c.provider_config_files, c.provider_config_files_hash = c.get_provider_config_files()

        return c

    def get_provider_config_files(self) -> Tuple[Dict[str, str], bytes]:
        tee_prov_configmap = self.config.run_configuration.provider_config.execution_controller_tee_prov_configmap
        source_files = {"manifests/configmap.execution-controller-tee-prov.yaml": tee_prov_configmap}

        if self.config.run_configuration.provider_config.sp_pki_challenge_secret is not None:
            sp_pki_challenge_secret = self.config.run_configuration.provider_config.sp_pki_challenge_secret
            source_files['manifests/secret.sp-pki-challenge.yaml'] = sp_pki_challenge_secret

        if (
            self.config.run_configuration.debug is True
            and self.app_config.text_config.vm_config.authorized_keys_file is not None
        ):
            source_files['authorized_keys'] = self.app_config.text_config.vm_config.authorized_keys_file

        source_files_hash = md5(json.dumps(source_files).encode('utf-8')).digest()
        return source_files, source_files_hash

    def get_cpu_params(self) -> list[str]:
        ret = []
        mode = self.config.qemu_configuration.mode
        if mode == VmQemuConfigMode.TDX:
            ret += ["-cpu", "host"]
        elif mode == VmQemuConfigMode.SEV_SNP:
            ret += ["-cpu", f"{snp_vcpu},phys-bits={phys_bits}"]
        else:
            ret += ["-cpu", "host"]
        return ret

    def get_gpu_pci_device_param(self, devices: list[Device]) -> list[str]:
        ret = []
        chassis_index = self.pci_device_count + 1
        ret += ["-fw_cfg", "name=opt/ovmf/X-PciMmio64,string=262144"]
        mode = self.config.qemu_configuration.mode
        for device in devices:
            ret += ["-device", f"pcie-root-port,id=pci.{chassis_index},bus=pcie.0,chassis={chassis_index}"]
            if mode == VmQemuConfigMode.TDX or mode == VmQemuConfigMode.SEV_SNP:
                ret += [
                    "-object",
                    f"iommufd,id=iommufd{chassis_index}",
                    "-device",
                    f"vfio-pci,host={device.pci_path},bus=pci.{chassis_index},iommufd=iommufd{chassis_index},romfile=",
                ]
            else:
                ret += ["-device", f"vfio-pci,host={device.pci_path},bus=pci.{chassis_index}"]
            self.pci_device_count += 1
        return ret

    def get_gpu_params(self) -> list[str]:
        ret = []
        self.pci_device_count = 0
        ret += self.get_gpu_pci_device_param(gpu_manager.gpu_devices)
        # ret += self.get_gpu_pci_device_param(gpu_manager.nvlink_devices)
        return ret

    def get_machine_params(self) -> list[str]:
        ret = []
        mode = self.config.qemu_configuration.mode
        if mode == VmQemuConfigMode.TDX:
            ret += ["-machine", "q35,kernel_irqchip=split,confidential-guest-support=tdx,memory-backend=mem0"]
        elif mode == VmQemuConfigMode.SEV_SNP:
            ret += ["-machine", "q35,confidential-guest-support=sev0,vmport=off"]
        else:
            ret += ["-machine", "q35,kernel_irqchip=split"]
        return ret

    def get_cpu_specific_args(self) -> list[str]:
        ret = []
        mode = self.config.qemu_configuration.mode
        if mode == VmQemuConfigMode.TDX:
            ret += ["-object", f"memory-backend-ram,id=mem0,size={self.config.qemu_configuration.mem_gb}G"]

            VMADDR_CID_HOST = 2  # https://man7.org/linux/man-pages/man7/vsock.7.html
            obj = {
                "qom-type": "tdx-guest",
                "id": "tdx",
                "quote-generation-socket": {"type": "vsock", "cid": str(VMADDR_CID_HOST), "port": "4050"},
            }
            ret += ["-object", json.dumps(obj)]

            ret += [
                "-device",
                f"vhost-vsock-pci,guest-cid={self.config.qemu_configuration.guest_cid}",
            ]
        elif mode == VmQemuConfigMode.SEV_SNP:
            ret += [
                "-object",
                f"sev-snp-guest,id=sev0,cbitpos={str(detected_cpu_cbitpos)},reduced-phys-bits=1,policy=0x30000,kernel-hashes=on",
            ]
        return ret

    def get_kernel_verify_args(self) -> list[str]:
        verity_scheme = "rootfs_verity.scheme=dm-verity"
        verity_hash = image_manager.get_release_rootfs_hash(self.config.run_configuration.vm_build)  # type: ignore[arg-type]
        if verity_hash is None:
            raise Exception(f'failed to get rootfs_hash for release: `{self.config.run_configuration.vm_build}`')
        verity_hash_str = f"rootfs_verity.hash={verity_hash}"
        return [verity_scheme, verity_hash_str]

    def get_kernel_cmdline(self) -> str:
        cmdline_arr = []
        cmdline_arr += ["root=LABEL=rootfs"]
        cmdline_arr += self.get_kernel_verify_args()

        if self.config.qemu_configuration.mode == VmQemuConfigMode.TDX:
            cmdline_arr += ["clearcpuid=mtrr"]
        elif self.config.qemu_configuration.mode == VmQemuConfigMode.SEV_SNP:
            cmdline_arr += [f"build={self.config.run_configuration.vm_build}", "pci=realloc,nocrs"]

        if self.config.run_configuration.debug is True:
            cmdline_arr += [
                "console=ttyS0",
                "systemd.log_level=trace",
                "systemd.log_target=log",
                f"argo_branch={self.config.run_configuration.argo_branch}",
                f"argo_sp_env={self.config.run_configuration.argo_sp_env}",
                "sp-debug=true",
            ]

        return ' '.join(cmdline_arr)

    def get_bios_path(self) -> str:
        bios_path = (
            image_manager.get_release_bios_amd_path(self.config.run_configuration.vm_build)  # type: ignore[arg-type]
            if self.config.qemu_configuration.mode == VmQemuConfigMode.SEV_SNP
            else image_manager.get_release_bios_path(self.config.run_configuration.vm_build)  # type: ignore[arg-type]
        )
        if bios_path is None:
            raise Exception(f'failed to get bios_path for release: `{self.config.run_configuration.vm_build}`')
        return bios_path

    def create_disk_image(self, target_file: str, img_type: str, size: str) -> None:
        __logger__.info(f'creating image: `{target_file}`, type: `{img_type}`, size: `{size}`')
        cmd = ['qemu-img', 'create', '-f', img_type, target_file, size]
        ret = subprocess.run(cmd, capture_output=True)
        if ret.returncode != 0:
            stdout = ret.stdout.decode('utf-8')
            stderr = ret.stderr.decode('utf-8')
            msg = f'{stdout} {stderr}'
            raise Exception(f'failed to create qemu img: `{target_file}`, reason: `{msg}`')

    def get_kernel_path(self) -> str:
        kernel_path = image_manager.get_release_kernel_path(self.config.run_configuration.vm_build)  # type: ignore[arg-type]
        if kernel_path is None:
            raise Exception(f'failed to get kernel_path for release: `{self.config.run_configuration.vm_build}`')
        return kernel_path

    def get_disks(self) -> list:
        ret = []

        image_path = image_manager.get_release_image_path(self.config.run_configuration.vm_build)  # type: ignore[arg-type]
        if image_path is None:
            raise Exception(f'failed to get image_path for release: `{self.config.run_configuration.vm_build}`')
        ret += ["-drive", f"file={image_path},if=virtio,format=raw,readonly=on"]

        state_disk_path = Path(self.config.qemu_configuration.cache_dir) / Path('state.qcow2')  # type: ignore[arg-type]
        # this function will be calleb before we knows is VM running or need to be runned, or rerunned
        # so we just need to set path, and creating, deleting will be performed later
        # state_disk_size = f'{self.config.qemu_configuration.state_disk_size_gb}G'
        # self.create_disk_image(target_file=state_disk_path, img_type="qcow2", state_disk_size)
        ret += ["-drive", f"file={state_disk_path},if=virtio,format=qcow2"]

        provider_config_disk_path = Path(self.config.qemu_configuration.cache_dir) / Path('provider_config.img')  # type: ignore[arg-type]
        # and the same about provider_config_disk_path
        # provider_config_disk_size = '1M'
        # self.create_disk_image(target_file=provider_config_disk_path, img_type="raw", provider_config_disk_size)
        ret += ["-drive", f"file={provider_config_disk_path},if=virtio,format=raw,readonly=on"]

        return ret

    def get_network_args(self) -> list[str]:
        ret = []
        port_forward_arr = []

        ip_addr = self.config.qemu_configuration.ip_address
        http_port = self.config.qemu_configuration.http_port
        if http_port is not None:
            port_forward_arr += [f"hostfwd=tcp:{ip_addr}:{http_port}-:80"]

        https_port = self.config.qemu_configuration.https_port
        if https_port is not None:
            port_forward_arr += [f"hostfwd=tcp:{ip_addr}:{https_port}-:443"]

        wg_port = self.config.qemu_configuration.wg_port
        if wg_port is not None:
            port_forward_arr += [f"hostfwd=udp:127.0.0.1:{wg_port}-:51820"]

        if self.config.run_configuration.debug is True:
            ssh_port = self.config.qemu_configuration.ssh_port
            port_forward_arr += [f"hostfwd=tcp:127.0.0.1:{ssh_port}-:22"]

        nic_0_id = 0  # has single qemu process scope
        nic_0_mac = self.config.qemu_configuration.mac_address  # has single qemu process scope (inside VM)
        ret += ["-device", f"virtio-net-pci,netdev=nic_id{nic_0_id},mac={nic_0_mac}"]
        ret += ["-netdev", f"user,id=nic_id{nic_0_id}" + ("," + ",".join(port_forward_arr) if port_forward_arr else "")]

        return ret

    def get_cmdline_from_config(self) -> list[str]:
        ret = []
        ret += [str(self.config.qemu_configuration.qemu_path)]
        ret += ["-enable-kvm"]
        ret += ["-nographic"]
        ret += ["-nodefaults"]
        ret += ["-vga", "none"]
        ret += ["-serial", "stdio"]
        ret += ["-smp", f"cores={self.config.qemu_configuration.cores}"]
        ret += ["-m", f"{self.config.qemu_configuration.mem_gb}G"]
        ret += ["-append", self.get_kernel_cmdline()]
        ret += ["-kernel", self.get_kernel_path()]
        ret += ["-bios", self.get_bios_path()]
        ret += self.get_machine_params()
        ret += self.get_cpu_params()
        ret += self.get_gpu_params()
        ret += self.get_cpu_specific_args()
        ret += self.get_disks()
        ret += self.get_network_args()
        return ret
