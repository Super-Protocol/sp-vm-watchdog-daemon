import logging
import time
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

        self.vms_from_config = [Qemu.load_from_config(vm) for vm in self.config.vm_configs]
        self.vms = self.constuct_vms_from_qemu()

    def constuct_vms_from_qemu(self) -> list[Daemonizer]:
        vms = []
        for vm in self.vms_from_config:
            vm_name = vm.config.name
            self.logger.info(f'processing vm: `{vm_name}`')
            pidfile = self.run_dir / Path(f"{vm_name}.pid")
            logfile = self.run_dir / Path(f"{vm_name}.log")
            vms.append(Daemonizer(vm, pidfile, logfile))
        return sorted(vms, key=lambda d: d.vm.config.name)

    def recreate_state_disk(self, vm: Qemu) -> None:
        state_disk_size = f'{vm.config.qemu_configuration.state_disk_size_gb}G'
        state_disk_path = Path(vm.config.qemu_configuration.cache_dir) / Path(
            'state.qcow2'
        )  # TODO: the same in qemu.py
        if state_disk_path.is_file():
            if is_file_in_use(state_disk_path):
                raise Exception(f"can't remove image: `{state_disk_path}`, some process still using it")
            state_disk_path.unlink()
        vm.create_disk_image(target_file=state_disk_path, img_type="qcow2", size=state_disk_size)

    def recreate_provider_config_disk(self, vm: Qemu) -> None:
        provider_config_disk_size = '1M'
        provider_config_disk_path = Path(vm.config.qemu_configuration.cache_dir) / Path(
            'provider_config.img'
        )  # TODO: the same in qemu.py
        if provider_config_disk_path.is_file():
            if is_file_in_use(provider_config_disk_path):
                raise Exception(f"can't remove image: `{provider_config_disk_path}`, some process still using it")
            provider_config_disk_path.unlink()
        vm.create_disk_image(target_file=provider_config_disk_path, img_type="raw", size=provider_config_disk_size)

        tee_prov_configmap = vm.config.run_configuration.provider_config.execution_controller_tee_prov_configmap
        source_files = {"configmap.execution-controller-tee-prov.yaml": tee_prov_configmap}

        if vm.config.run_configuration.provider_config.sp_pki_challenge_secret is not None:
            sp_pki_challenge_secret = vm.config.run_configuration.provider_config.sp_pki_challenge_secret
            source_files['secret.sp-pki-challenge.yaml'] = sp_pki_challenge_secret

        prepare_provider_config_disk(image_path=provider_config_disk_path, source_files=source_files)

    def start_vm(self, d: Daemonizer) -> None:
        # ensure state disk
        # ensure provider config
        # ensure GPU
        self.logger.info(f'starting vm: `{d.vm.config.name}`')

        if d.is_running():
            raise Exception(f'vm: `{d.vm.name}` is already running')

        self.recreate_state_disk(d.vm)
        self.recreate_provider_config_disk(d.vm)
        d.start()

    def stop_vm(self, d: Daemonizer) -> None:
        self.logger.info(f'stopping vm: `{d.vm.config.name}`')
        # graceful until timeout
        # kill if timeout
        # remove state disk
        # remove provider config
        pass

    def restart_vm(self, d: Daemonizer) -> None:
        self.stop_vm(d)
        self.start_vm(d)

    def run(self):
        self.logger.info(f'started, found: `{len(self.vms)}` VMs')
        while True:
            for d in self.vms:
                self.logger.info(f'checking vm: `{d.vm.config.name}`')
                if not d.is_running():
                    self.logger.info(f"vm: `{d.vm.config.name}` isn't running, starting")
                    self.start_vm(d)
                # elif cmdline != vm.cmdline():
                #    self.logger.info(f"vm: `{d.vm_name}` parameters changed, restarting")
                #    self.restart_vm(d)
                elif not d.is_healthy():
                    self.logger.info(f"vm: `{d.vm.config.name}` isn't healthy, restarting")
                    self.restart_vm(d)
            time.sleep(10)
