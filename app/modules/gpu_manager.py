import subprocess
import logging
import re

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
        self.vendor_id = "10de:"
        self.device_class_name = "3D controller"

        self.lspci_regex_main = re.compile(
            r'^(?P<pci_address>[a-f\d]+:[a-f\d]+:[a-f\d]+\.[0-7])\W(?P<device_type>.+)\W\[(?P<device_type_id>[a-f\d]+)\]:\W(?P<device_name>.+)\W\[(?P<vendor_id>[a-f\d]+):(?P<device_id>[a-f\d]+)\]'
        )
        self.lspci_regex_subsystem = re.compile(r'^\tSubsystem:\W(?P<subsystem>.+)$')
        self.lspci_regex_driver = re.compile(r'^\tKernel driver in use:\W(?P<driver>.+)$')
        self.lspci_regex_modules = re.compile(r'^\tKernel modules:\W(?P<modules>.+)$')

        self.requred_kernel_modules = ('vfio', 'vfio-pci')
        self.logger = logging.getLogger(__name__)

        self.devices = []

        self.init_modules()
        self.find_gpu_on_system()

    def init_modules(self) -> None:
        self.logger.info(f'initializing kernel modules: {self.requred_kernel_modules}')
        [modprobe(m) for m in self.requred_kernel_modules]

    def find_gpu_on_system(self) -> list[Device]:
        self.logger.info(
            f'searching GPUs on system, with class: `{self.device_class_name}` and vendor id: `{self.vendor_id}`'
        )
        ret = subprocess.run(["lspci", "-nnk", "-d", self.vendor_id], capture_output=True)
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
                if self.device_class_name not in line:
                    continue
                found_device = Device(name=match.group('device_name'), pci_path=match.group('pci_address'))
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

        self.devices = devices
        return devices

    def replace_driver(self, pci_path: str, driver_name: str) -> None:
        self.logging.info(f'replacing driver for: `{pci_path}`, to: `{driver_name}`')
        device = next(iter([x for x in self.devices if x.pci_path == pci_path]), None)
        if device is None:
            raise Exception(f'failed to replace driver for: `{pci_path}`, reason: device not in self.devices')

        driver_path = Path('/sys/bus/pci/drivers') / Path(driver_name)
        if not driver_path.is_dir():
            raise Exception(
                f'failed to replace driver for: `{pci_path}`, reason: driver path `{driver_path}` not found'
            )

        sysfs_device_path = Path(f'/sys/bus/pci/devices/{pci_path}')
        if not sysfs_device_path.is_dir():
            raise Exception(f'failed to replace driver for: `{pci_path}`, reason: path `{sysfs_device_path}` not found')

        current_driver_link_file = sysfs_device_path / Path('driver')
        # https://code.google.com/archive/p/pci-hacking/wikis/bind_Uunbind_PCI.wiki
        if current_driver_link_file.is_symlink():
            current_driver = current_driver_link_file.resolve()
            self.logger.info(f'unbinding already binded driver: `{current_driver}` for device: `{pci_path}`')
            with current_driver.open('w') as f:
                f.write_text(pci_path)

        driver_override_path = sysfs_device_path / Path('driver_override')
        if not driver_override_path.is_file():
            raise Exception(
                f'failed to replace driver for: `{pci_path}`, reason: path `{driver_override_path}` not found'
            )

        with driver_override_path.open('w') as f:
            f.write_text(driver_name)

        driver_bind_path = driver_path / Path('bind')
        if not driver_bind_path.is_file():
            raise Exception(f'failed to replace driver for: `{pci_path}`, reason: path `{driver_bind_path}` not found')

        with driver_bind_path.open('w') as f:
            f.write_text(pci_path)

        if not current_driver_link_file.is_symlink() or current_driver_link_file.resolve() != driver_path:
            raise Exception(f'failed to replace driver for: `{pci_path}`, reason: unknown error')

        device.driver_in_use = driver_name


# gpu_manager: GpuManager | None = None
gpu_manager = GpuManager()
