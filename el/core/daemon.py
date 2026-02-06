"""EL Daemon - The main entry point that keeps EL running 24/7."""

import asyncio
import logging
import signal
import sys
from el.config.settings import ELConfig, ensure_dirs
from el.telegram.bot import ELBot

logger = logging.getLogger("el")


def setup_logging(debug: bool = False):
    """Configure logging for EL."""
    level = logging.DEBUG if debug else logging.INFO
    formatter = logging.Formatter(
        "[%(asctime)s] %(name)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)

    # Root logger
    root = logging.getLogger("el")
    root.setLevel(level)
    root.addHandler(console)

    # Suppress noisy libs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


class ELDaemon:
    """Main daemon that orchestrates all EL components."""

    def __init__(self, config: ELConfig = None, debug: bool = False):
        self.config = config or ELConfig.load()
        self.debug = debug
        self.bot: ELBot = None

    async def start(self):
        """Start EL."""
        setup_logging(self.debug)
        ensure_dirs()

        logger.info("=" * 50)
        logger.info("  EL - Personal AI Agent")
        logger.info("  Starting up...")
        logger.info("=" * 50)

        self.bot = ELBot(self.config)

        # Handle shutdown signals
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

        await self.bot.run()

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("EL shutting down gracefully...")
        if self.bot:
            self.bot.scheduler.stop()
            if self.bot.memory:
                self.bot.memory.close()
        sys.exit(0)


def run(debug: bool = False):
    """Entry point to run EL as a daemon."""
    config = ELConfig.load()
    daemon = ELDaemon(config, debug=debug)
    asyncio.run(daemon.start())
