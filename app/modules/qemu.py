from pydantic import model_validator, BaseModel, Field

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
            args += ["clearcpuid=mtrr", f"-device vhost-vsock-pci,guest-cid={self.config.qemu_configuration.guest_cid}"]
        elif mode == VmQemuConfigMode.SEV_SNP:
            args += [f"build={self.config.run_configuration.vm_build}"]
        return args

    def get_kernel_verify_args(self) -> list[str]:
        verity_scheme = "rootfs_verity.scheme=dm-verity"
        verity_hash = f"rootfs_verity.hash="
        return [verity_scheme, verity_hash]

    def get_kernel_cmdline(self) -> str:
        rootfs_arg = "root=LABEL=rootfs"
        return ' '.join([rootfs_arg] + self.get_kernel_verify_args() + self.get_cpu_specific_args())

    def get_cmdline_from_config(self) -> list[str]:
        ret = [
            str(self.config.qemu_configuration.qemu_path),
            "-enable-kvm",
            "-append",
            self.get_kernel_cmdline(),
        ]
        return ret
