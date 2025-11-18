import subprocess
import logging
import sys
import re
import os
from pathlib import Path

import jc
from pydantic import BaseModel, Field

from .utils import modprobe

# gpu_admin_tools_dir = Path(os.path.dirname(__file__)).parent.parent / Path('lib/gpu_admin_tools')
# sys.path.insert(0, gpu_admin_tools_dir)
# print(sys.path)
# from . import nvidia_gpu_tools


class Device(BaseModel):
    name: str
    vendor: str
    pci_path: str
    driver_in_use: str | None = None


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
        ret = subprocess.run(["lspci", "-nnmmkv", "-d", vendor_id], capture_output=True)
        stdout = ret.stdout.decode('utf-8')

        if ret.returncode != 0:
            stderr = ret.stderr.decode('utf-8')
            msg = f'{stdout} {stderr}'
            raise Exception(f'failed to get devices from `lscpi`: `target_file`, reason: `{msg}`')

        res = jc.parse('lspci', stdout)

        # devices = [
        #    Device(
        #        name=d.get('device'),
        #        pci_path=f'0000:{d.get("slot")}',
        #        vendor=d.get('vendor'),
        #        driver_in_use=d.get('driver', None),
        #    )
        #    for d in res
        #    if d.get('class', None) == device_class_name
        # ]

        devices = []
        for d in res:
            if d.get('class', None) != device_class_name:
                continue

            domain_int = d.get("domain_int")
            domain_hex = f"{domain_int:04x}"
            slot = d.get("slot")
            devices.append(
                Device(
                    name=d.get('device'),
                    pci_path=f"{domain_hex}:{slot}",
                    vendor=d.get('vendor'),
                    driver_in_use=d.get('driver', None),
                )
            )

        if len(devices):
            self.logger.info(f'found {len(devices)} devices: `{devices}`')

        return devices

    def replace_driver(self, device: Device, driver_name: str) -> None:
        self.logger.info(f'replacing driver for: `{device.pci_path}`, to: `{driver_name}`')
        driver_path = Path('/sys/bus/pci/drivers') / Path(driver_name)
        device_pci_path = device.pci_path
        if not driver_path.is_dir():
            raise Exception(
                f'failed to replace driver for: `{device_pci_path}`, reason: driver path `{driver_path}` not found'
            )
        sysfs_device_path = Path(f'/sys/bus/pci/devices/{device_pci_path}')
        if not sysfs_device_path.is_dir():
            raise Exception(
                f'failed to replace driver for: `{device_pci_path}`, reason: path `{sysfs_device_path}` not found'
            )

        current_driver_link_file = sysfs_device_path / Path('driver')
        # https://code.google.com/archive/p/pci-hacking/wikis/bind_Uunbind_PCI.wiki
        if current_driver_link_file.is_symlink():
            current_driver = current_driver_link_file.resolve()
            self.logger.info(f'unbinding already binded driver: `{current_driver}` for device: `{device_pci_path}`')
            current_driver_unbind = current_driver / Path('unbind')
            current_driver_unbind.write_text(device_pci_path)

        driver_override_path = sysfs_device_path / Path('driver_override')
        if not driver_override_path.is_file():
            raise Exception(
                f'failed to replace driver for: `{device_pci_path}`, reason: path `{driver_override_path}` not found'
            )

        driver_override_path.write_text(driver_name)

        driver_bind_path = driver_path / Path('bind')
        if not driver_bind_path.is_file():
            raise Exception(
                f'failed to replace driver for: `{device_pci_path}`, reason: path `{driver_bind_path}` not found'
            )

        driver_bind_path.write_text(device_pci_path)

        if not current_driver_link_file.is_symlink() or current_driver_link_file.resolve() != driver_path:
            raise Exception(f'failed to replace driver for: `{device_pci_path}`, reason: unknown error')

        device.driver_in_use = driver_name

    def replace_drivers_to_vfio(self, devices: list[Device]) -> None:
        for device in devices:
            if device.driver_in_use != "vfio-pci":
                self.replace_driver(device, "vfio-pci")


# gpu_manager: GpuManager | None = None
gpu_manager = GpuManager()
