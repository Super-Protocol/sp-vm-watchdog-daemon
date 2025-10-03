from pydantic import model_validator, BaseModel, Field

from .image_manager import image_manager
from .models import VmQemuConfigMode
from .config import VmConfig

#    QEMU_COMMAND="${QEMU_PATH} \
#        -enable-kvm \
#        -append \"${KERNEL_CMD_LINE}\" \
#        -drive file=${IMAGE_PATH},if=virtio,format=raw,readonly=on \
#        -drive file=${STATE_DISK_PATH},if=virtio,format=qcow2 \
#        -drive file=${PROVIDER_CONFIG_DISK_PATH},if=virtio,format=raw,readonly=on \
#        -kernel ${KERNEL_PATH} \
#        -smp cores=${VM_CPU} \
#        -m ${VM_RAM}G \
#        ${CPU_PARAMS} \
#        -machine ${MACHINE_PARAMS} \
#        ${CC_SPECIFIC_PARAMS} \
#        ${NETWORK_SETTINGS} \
#        -nographic \
#        ${CC_PARAMS} \
#        -bios ${BIOS_PATH} \
#        -vga none \
#        -nodefaults \
#        -serial stdio \
#        -device vhost-vsock-pci,guest-cid=${GUEST_CID} \
#        ${GPU_PASSTHROUGH} \
#        "


class Qemu(BaseModel):
    config: VmConfig
    cmd: list[str] | None = None

    @classmethod
    def load_from_config(cls, config: VmConfig) -> "Qemu":
        return cls(config=config)

    def get_cpu_specific_args(self) -> list[str]:
        args = []
        mode = self.config.qemu_configuration.mode
        if mode == VmQemuConfigMode.TDX:
            args += ["clearcpuid=mtrr"]
            args += [
                "-device",
                f"vhost-vsock-pci,guest-cid={self.config.qemu_configuration.guest_cid}",
            ]
        elif mode == VmQemuConfigMode.SEV_SNP:
            args += [f"build={self.config.run_configuration.vm_build}"]
        return args

    def get_kernel_verify_args(self) -> list[str]:
        verity_scheme = "rootfs_verity.scheme=dm-verity"
        verity_hash = image_manager.get_release_rootfs_hash(self.config.run_configuration.vm_build)
        if verity_hash is None:
            raise Exception(f'failed to get rootfs_hash for release: `{self.config.run_configuration.vm_build}`')
        verity_hash_str = f"rootfs_verity.hash={verity_hash}"
        return [verity_scheme, verity_hash_str]

    def get_kernel_cmdline(self) -> str:
        rootfs_arg = "root=LABEL=rootfs"
        return ' '.join([rootfs_arg] + self.get_kernel_verify_args())

    def get_bios_path(self) -> str:
        bios_path = (
            image_manager.get_release_bios_amd_path(self.config.run_configuration.vm_build)
            if self.config.qemu_configuration.mode == VmQemuConfigMode.SEV_SNP
            else image_manager.get_release_bios_path(self.config.run_configuration.vm_build)
        )
        if bios_path is None:
            raise Exception(f'failed to get bios_path for release: `{self.config.run_configuration.vm_build}`')
        return bios_path

    def get_disks(self) -> str:
        ret = []

        image_path = image_manager.get_release_image_path(self.config.run_configuration.vm_build)
        if image_path is None:
            raise Exception(f'failed to get image_path for release: `{self.config.run_configuration.vm_build}`')
        ret += ["-drive", f"file={image_path},if=virtio,format=raw,readonly=on"]

        # ret += ["-drive", f"file=${STATE_DISK_PATH},if=virtio,format=qcow2"]
        # ret += ["-drive", f"file=${PROVIDER_CONFIG_DISK_PATH},if=virtio,format=raw,readonly=on"]
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
        ret += ["-bios", self.get_bios_path()]
        ret += self.get_cpu_specific_args()
        ret += self.get_disks()
        return ret
