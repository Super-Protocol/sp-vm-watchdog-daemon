#!/usr/bin/env python3

import argparse
import logging
import time

from modules import image_manager, gpu_manager, VmManager, AppConfig, Qemu


def parseArgs() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Daemon to control the SuperProtocol VMs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", help="Main config file", default="/etc/sp/watchdog/config.json")
    parser.add_argument("--log-level", help="Log level", default="INFO")
    return parser.parse_args()


def init_logging(level_str: str) -> None:
    level = getattr(logging, level_str.upper(), None)
    if level is None:
        raise Exception(f"wrong log level: {level_str}")
    logging.basicConfig(level=level, format="%(asctime)s [%(name)s] [%(levelname)s]: %(message)s")


def main():
    args = parseArgs()
    init_logging(args.log_level)

    conf = AppConfig.load(filename=args.config)
    vm_manager = VmManager(config=conf)

    while True:
        try:
            vm_manager.run()
        except Exception as e:
            logging.exception(e)
            time.sleep(60)


if __name__ == "__main__":
    main()
