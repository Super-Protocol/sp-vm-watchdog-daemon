import logging
import time
from datetime import datetime
from pathlib import Path

from .daemonizer import Daemonizer
from .config import AppConfig
from .utils import prepare_provider_config_disk, is_file_in_use
from .qemu import Qemu


class VmManager:
    def __init__(self, config: AppConfig):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.run_dir = Path('/var/run/sp/watchdog/vms')
        self.run_dir.mkdir(exist_ok=True, parents=True)

        self.vms_from_config = [
            Qemu.load_from_config(app_config=self.config, config=vm) for vm in self.config.vm_configs
        ]
        self.vms = self.constuct_vms_from_qemu()

    def constuct_vms_from_qemu(self) -> list[Daemonizer]:
        vms = []
        for vm in self.vms_from_config:
            vm_name = vm.config.name
            self.logger.info(f'processing vm: `{vm_name}`')
            pidfile = self.run_dir / Path(f"{vm_name}.pid")
            logfile = self.run_dir / Path(f"{vm_name}.log")
            config_hash_file = self.run_dir / Path(f"{vm_name}.config_hash")
            vms.append(Daemonizer(vm, pid_file=pidfile, log_file=logfile, config_hash_file=config_hash_file))
        return sorted(vms, key=lambda d: d.vm.config.name)

    def recreate_state_disk(self, vm: Qemu) -> None:
        if vm.state_disk_path.is_file():
            if is_file_in_use(vm.state_disk_path):
                raise Exception(f"can't remove image: `{vm.state_disk_path}`, some process still using it")
            vm.state_disk_path.unlink()

        state_disk_size = f'{vm.config.qemu_configuration.state_disk_size_gb}G'
        vm.create_disk_image(target_file=vm.state_disk_path, img_type="qcow2", size=state_disk_size)

    def recreate_provider_config_disk(self, vm: Qemu) -> None:
        if vm.provider_config_disk_path.is_file():
            if is_file_in_use(vm.provider_config_disk_path):
                raise Exception(f"can't remove image: `{vm.provider_config_disk_path}`, some process still using it")
            vm.provider_config_disk_path.unlink()

        provider_config_disk_size = '1M'
        vm.create_disk_image(target_file=vm.provider_config_disk_path, img_type="raw", size=provider_config_disk_size)

        prepare_provider_config_disk(image_path=vm.provider_config_disk_path, source_files=vm.provider_config_files)

    def start_vm(self, d: Daemonizer) -> None:
        # TODO: ensure GPU
        self.logger.info(f'starting vm: `{d.vm.config.name}`')

        if d.is_running():
            raise Exception(f'vm: `{d.vm.config.name}` is already running')

        d.write_config_hash(d.vm.provider_config_files_hash)
        self.recreate_state_disk(d.vm)
        self.recreate_provider_config_disk(d.vm)
        d.start()

    def stop_vm(self, d: Daemonizer) -> None:
        self.logger.info(f'stopping vm: `{d.vm.config.name}`')
        d.stop()
        d.remove_config_hash_file()

    def restart_vm(self, d: Daemonizer) -> None:
        self.stop_vm(d)
        self.start_vm(d)

    def is_configuration_changed(self, d: Daemonizer) -> bool:
        if sorted(d.vm.cmd) != sorted(d.get_process_cmdline()):
            return True
        if not d.vm.provider_config_disk_path.exists():
            return False
        provider_config_ctime = datetime.fromtimestamp(d.vm.provider_config_disk_path.stat().st_ctime)
        for target_name, source_path in d.vm.provider_config_files.items():
            source_filepath = Path(source_path)
            source_file_mtime = datetime.fromtimestamp(source_filepath.stat().st_mtime)
            if source_file_mtime > provider_config_ctime:
                return True
            provider_config_files_hash_new = d.vm.provider_config_files_hash
            provider_config_files_hash_old = d.get_config_hash_from_file()
            if provider_config_files_hash_new != provider_config_files_hash_old:
                return True
        return False

    def run(self):
        polling_interval = 10
        self.logger.info(f'started, found: `{len(self.vms)}` VMs')
        self.logger.info(f'polling interval is `{polling_interval}` sec')
        while True:
            for d in self.vms:
                self.logger.info(f'checking vm: `{d.vm.config.name}`')
                if not d.is_running():
                    self.logger.info(f"vm: `{d.vm.config.name}` isn't running, starting")
                    self.start_vm(d)
                elif self.is_configuration_changed(d):
                    self.logger.info(f"vm: `{d.vm.config.name}` parameters changed, restarting")
                    self.restart_vm(d)
                elif not d.is_healthy():
                    self.logger.info(f"vm: `{d.vm.config.name}` isn't healthy, restarting")
                    self.restart_vm(d)
                else:
                    self.logger.info(f'vm: `{d.vm.config.name}` is ok')
            time.sleep(polling_interval)
