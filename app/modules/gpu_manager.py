import subprocess
import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

from .utils import modprobe


class Device(BaseModel):
    name: str
    pci_path: str
    subsystem: str | None = None
    driver_in_use: str | None = None
    kernel_modules: list[str] = Field(default_factory=list)


class GpuManager:
    def __init__(self):
        self.lspci_regex_main = re.compile(
            r'^(?P<pci_address>[a-f\d]+:[a-f\d]+.[a-f\d])\W(?P<device_type>.+)\W\[(?P<device_type_id>[a-f\d]+)\]:\W(?P<device_name>.+)\W\[(?P<vendor_id>[a-f\d]+):(?P<device_id>[a-f\d]+)\]'
        )
        self.lspci_regex_subsystem = re.compile(r'^\tSubsystem:\W(?P<subsystem>.+)$')
        self.lspci_regex_driver = re.compile(r'^\tKernel driver in use:\W(?P<driver>.+)$')
        self.lspci_regex_modules = re.compile(r'^\tKernel modules:\W(?P<modules>.+)$')

        self.requred_kernel_modules = ('vfio', 'vfio-pci')
        self.logger = logging.getLogger(__name__)

        self.gpu_devices = self.find_pci_devices("10de:", "3D controller")

        self.init_modules()
        self.replace_drivers_to_vfio(self.gpu_devices)

    def init_modules(self) -> None:
        self.logger.info(f'initializing kernel modules: {self.requred_kernel_modules}')
        for m in self.requred_kernel_modules:
            modprobe(m)

    def find_pci_devices(self, vendor_id: str, device_class_name: str) -> list[Device]:
        self.logger.info(
            f'searching pci devices on system, with class: `{device_class_name}` and vendor id: `{vendor_id}`'
        )
        ret = subprocess.run(["lspci", "-nnk", "-d", vendor_id], capture_output=True)
        stdout = ret.stdout.decode('utf-8')

        if ret.returncode != 0:
            stderr = ret.stderr.decode('utf-8')
            msg = f'{stdout} {stderr}'
            raise Exception(f'failed to get devices from `lscpi`: `target_file`, reason: `{msg}`')

        devices = []

        lines = stdout.splitlines()
        found_device = None
        # why lscpi has no json output format options?....((9(99(9(
        for line in lines:
            # first line in device block
            match = self.lspci_regex_main.match(line)
            if match:
                found_device = None
                if device_class_name not in line:
                    continue

                pci_path_match = match.group('pci_address')
                if pci_path_match is None:
                    raise Exception(
                        f'failed to extract pci_address from: `{line}`, reason: pci_address group not found'
                    )

                device_name_match = match.group('device_name')
                if device_name_match is None:
                    raise Exception(
                        f'failed to extract device_name from: `{line}`, reason: device_name group not found'
                    )

                pci_path = f"0000:{pci_path_match}"
                found_device = Device(name=device_name_match, pci_path=pci_path)
                continue

            if found_device is None:
                continue

            # second
            subsystem_match = self.lspci_regex_subsystem.match(line)
            if subsystem_match:
                found_device.subsystem = subsystem_match.group('subsystem')
                continue

            # third
            driver_match = self.lspci_regex_driver.match(line)
            if driver_match:
                found_device.driver_in_use = driver_match.group('driver')
                continue

            # last line in device block
            kernel_modules_match = self.lspci_regex_modules.match(line)
            if kernel_modules_match:
                found_device.kernel_modules = kernel_modules_match.group('modules').split(', ')
                devices.append(found_device)
                found_device = None

        if len(devices):
            self.logger.info(f'found {len(devices)} devices: `{devices}`')

        return devices

    def replace_driver(self, device: Device, driver_name: str) -> None:
        self.logger.info(f'replacing driver for: `{device.pci_path}`, to: `{driver_name}`')
        driver_path = Path('/sys/bus/pci/drivers') / Path(driver_name)
        if not driver_path.is_dir():
            raise Exception(
                f'failed to replace driver for: `{device.pci_path}`, reason: driver path `{driver_path}` not found'
            )
        sysfs_device_path = Path(f'/sys/bus/pci/devices/{device.pci_path}')
        if not sysfs_device_path.is_dir():
            raise Exception(
                f'failed to replace driver for: `{device.pci_path}`, reason: path `{sysfs_device_path}` not found'
            )

        current_driver_link_file = sysfs_device_path / Path('driver')
        # https://code.google.com/archive/p/pci-hacking/wikis/bind_Uunbind_PCI.wiki
        if current_driver_link_file.is_symlink():
            current_driver = current_driver_link_file.resolve()
            self.logger.info(f'unbinding already binded driver: `{current_driver}` for device: `{device.pci_path}`')
            current_driver_unbind = current_driver / Path('unbind')
            current_driver_unbind.write_text(device.pci_path)

        driver_override_path = sysfs_device_path / Path('driver_override')
        if not driver_override_path.is_file():
            raise Exception(
                f'failed to replace driver for: `{device.pci_path}`, reason: path `{driver_override_path}` not found'
            )

        driver_override_path.write_text(driver_name)

        driver_bind_path = driver_path / Path('bind')
        if not driver_bind_path.is_file():
            raise Exception(
                f'failed to replace driver for: `{device.pci_path}`, reason: path `{driver_bind_path}` not found'
            )

        driver_bind_path.write_text(device.pci_path)

        if not current_driver_link_file.is_symlink() or current_driver_link_file.resolve() != driver_path:
            raise Exception(f'failed to replace driver for: `{device.pci_path}`, reason: unknown error')

        device.driver_in_use = driver_name

    def replace_drivers_to_vfio(self, devices: list[Device]) -> None:
        for device in devices:
            if device.driver_in_use is not "vfio-pci":
                self.replace_driver(device, "vfio-pci")


# gpu_manager: GpuManager | None = None
gpu_manager = GpuManager()
