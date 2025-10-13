import logging
from pathlib import Path

import grpc
from pydantic import BaseModel

from .proto import sp_vm_downloader_pb2_grpc, sp_vm_downloader_pb2


class ImageManager:
    cached_latest_github_release: str | None
    release_paths: dict

    def __init__(self, socket_path: str):
        self.logger = logging.getLogger(__name__)
        self.socket_path = socket_path

        self.cached_latest_github_release = None
        self.release_paths = dict()

    def update_cached_latest_github_release(self) -> bool:
        if not Path(self.socket_path).is_socket():
            self.logger.error(
                f'failed to get latest github release from sp_vm_downloader because sp_vm_downloader is down'
            )
            return False

        self.logger.info(f'getting latest github release from sp_vm_downloader')
        with grpc.insecure_channel(f"unix://{self.socket_path}") as channel:
            stub = sp_vm_downloader_pb2_grpc.SpVmDownloaderStub(channel)
            response = stub.GetLatestGithubReleaseName(sp_vm_downloader_pb2.Empty())
            if response.success != True:
                self.logger.error(
                    f'failed to get latest github release from sp_vm_downloader, reason: `{response.msg}`'
                )
            else:
                self.cached_latest_github_release = response.name
            return response.success

    def get_release_path(self, release: str) -> str | None:
        release_path = self.release_paths.get(release)
        if release_path is not None:
            return release_path

        if not Path(self.socket_path).is_socket():
            self.logger.error(
                f'failed to get release: `{release}` from sp_vm_downloader because sp_vm_downloader is down'
            )
            return None

        self.logger.info(f'getting release path for release: `{release}` from sp_vm_downloader')
        with grpc.insecure_channel(f"unix://{self.socket_path}") as channel:
            stub = sp_vm_downloader_pb2_grpc.SpVmDownloaderStub(channel)
            response = stub.GetRelease(sp_vm_downloader_pb2.ReleaseRequest(name=release))
            if response.success != True:
                self.logger.error(f'failed to get release: `{release}` from sp_vm_downloader, reason: `{response.msg}`')
            else:
                self.release_paths[release] = response.path
            return response.path

    def get_release_image_path(self, release: str) -> str | None:
        release_path = self.get_release_path(release)
        if release_path is None:
            return None

        rootfs_image_path = Path(release_path) / Path(f'sp-vm-{release}.img')
        if not rootfs_image_path.is_file():
            self.logger.error(f'failed to get release rootfs image path for release: `{release}`: not found')
            return None
        return str(rootfs_image_path)

    def get_release_kernel_path(self, release: str) -> str | None:
        release_path = self.get_release_path(release)
        if release_path is None:
            return None

        kernel_path = Path(release_path) / Path(f'vmlinuz')
        if not kernel_path.is_file():
            self.logger.error(f'failed to get release kernel path for release: `{release}`: not found')
            return None
        return str(kernel_path)

    def get_release_bios_path(self, release: str) -> str | None:
        release_path = self.get_release_path(release)
        if release_path is None:
            return None

        bios_path = Path(release_path) / Path(f'OVMF.fd')
        if not bios_path.is_file():
            self.logger.error(f'failed to get release bios path for release: `{release}`: not found')
            return None
        return str(bios_path)

    def get_release_bios_amd_path(self, release: str) -> str | None:
        release_path = self.get_release_path(release)
        if release_path is None:
            return None

        bios_amd_path = Path(release_path) / Path(f'OVMF_AMD.fd')
        if not bios_amd_path.is_file():
            self.logger.error(f'failed to get release bios amd path for release: `{release}`: not found')
            return None
        return str(bios_amd_path)

    def get_latest_github_release(self) -> str | None:
        if self.cached_latest_github_release is None:
            if self.update_cached_latest_github_release() is False:
                raise Exception(f'failed to init ImageManager')
            if self.cached_latest_github_release is None:
                raise Exception(f'failed to init ImageManager')
        return self.cached_latest_github_release

    def get_release_rootfs_hash(self, release: str) -> str | None:
        release_path = self.get_release_path(release)
        if release_path is None:
            return None

        rootfs_hash_path = Path(release_path) / Path('rootfs_hash.txt')
        if not rootfs_hash_path.is_file():
            self.logger.error(f'failed to get release rootfs hash from: `{rootfs_hash_path}`: not found')
            return None
        return rootfs_hash_path.read_text(encoding="utf-8").strip()


# image_manager: ImageManager | None = None
image_manager = ImageManager("/var/run/sp-vm-downloader.sock")
