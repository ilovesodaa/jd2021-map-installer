"""Headless CLI mode for the JD2021 Map Installer."""

import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from jd2021_installer.core.config import AppConfig
from jd2021_installer.ui.workers.pipeline_workers import install_map_to_game

logger = logging.getLogger("jd2021.cli")

def run_cli(args) -> int:
    """Entry point for headless CLI operation."""
    # 1. Setup logging for CLI
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    
    # 2. Load/override config
    config = AppConfig()
    if args.game_dir:
        config.game_directory = Path(args.game_dir)
        
    if not config.game_directory or not config.game_directory.is_dir():
        logger.error("Error: Game directory is not set or invalid. Use --game-dir.")
        return 1
        
    if not args.target:
        logger.error("Error: No input target provided. Use --target.")
        return 1

    # 3. Setup SIGINT handling
    def sigint_handler(sig, frame):
        logger.info("\nInterrupted by user. Exiting...")
        sys.exit(0)
    signal.signal(signal.SIGINT, sigint_handler)

    logger.info("=== JD2021 Map Installer V2 (CLI) ===")
    logger.info(f"Mode: {args.mode}")
    logger.info(f"Target: {args.target}")
    logger.info(f"Game Directory: {config.game_directory}")
    logger.info("-------------------------------------")

    try:
        # 4. Mode dispatch
        if args.mode == "fetch":
            # For simplicity, we'll implement a basic CLI-based fetch or 
            # reuse the Playwright logic headlessly.
            # Currently V2 fetch relies on a browser.
            from jd2021_installer.extractors.web_playwright import PlaywrightWebExtractor
            extractor = PlaywrightWebExtractor(config=config)
            
            logger.info(f"Starting fetch for: {args.target}")
            # This would normally be in a worker; running directly here
            # Note: Playwright needs a running loop or sync context
            # For brevity in this V2 gap-filling session, we'll assume 
            # direct Normalization of a pre-existing cache or downloaded file if possible.
            # But let's try to make it work.
            
            raise NotImplementedError("Headless browser fetch not yet fully wired to CLI.")

        elif args.mode == "ipk":
            from jd2021_installer.extractors.archive_ipk import ArchiveIPKExtractor
            from jd2021_installer.parsers.normalizer import normalize
            
            ipk_path = Path(args.target)
            if not ipk_path.is_file():
                logger.error(f"IPK file not found: {ipk_path}")
                return 1
                
            extractor = ArchiveIPKExtractor(ipk_path)
            cache_dir = config.cache_directory / ipk_path.stem
            logger.info(f"Unpacking {ipk_path.name}...")
            map_dir = extractor.extract(cache_dir)
            
            logger.info("Normalizing...")
            map_data = normalize(map_dir)
            
            logger.info("Installing...")
            install_map_to_game(
                map_data, 
                config.game_directory, 
                config, 
                status_callback=lambda s: logger.info(f"  {s}")
            )
            
        elif args.mode == "manual":
            from jd2021_installer.parsers.normalizer import normalize
            root = Path(args.target)
            if not root.is_dir():
                logger.error(f"Manual directory not found: {root}")
                return 1
                
            logger.info("Normalizing...")
            map_data = normalize(root)
            
            logger.info("Installing...")
            install_map_to_game(
                map_data, 
                config.game_directory, 
                config, 
                status_callback=lambda s: logger.info(f"  {s}")
            )
            
        else:
            logger.error(f"Mode '{args.mode}' not yet supported in CLI.")
            return 1

        logger.info("-------------------------------------")
        logger.info("✅  All tasks completed successfully!")
        return 0

    except Exception as e:
        logger.exception(f"FATAL ERROR: {e}")
        return 1
