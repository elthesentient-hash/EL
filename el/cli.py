"""EL CLI - Command line interface for managing EL."""

import argparse
import sys
import json
from el.config.settings import ELConfig, EL_HOME, EL_CONFIG_FILE, ensure_dirs


def cmd_start(args):
    """Start EL daemon."""
    from el.core.daemon import run
    run(debug=args.debug)


def cmd_setup(args):
    """Interactive setup for EL."""
    ensure_dirs()
    config = ELConfig.load()

    print("=" * 50)
    print("  EL Setup")
    print("  Let's get you configured.")
    print("=" * 50)
    print()

    # Telegram
    token = input("Telegram Bot Token (from @BotFather): ").strip()
    if token:
        config.telegram.bot_token = token

    user_id = input("Your Telegram User ID (numbers only): ").strip()
    if user_id:
        config.telegram.allowed_user_ids = [int(user_id)]

    # Voice
    print("\nVoice Settings:")
    print("  STT models: tiny (fast), base (balanced), small, medium, large (best)")
    stt = input(f"Whisper model [{config.voice.stt_model}]: ").strip()
    if stt:
        config.voice.stt_model = stt

    print("\n  TTS engines: bark (human-like, needs GPU), piper (lighter)")
    tts = input(f"TTS engine [{config.voice.tts_engine}]: ").strip()
    if tts:
        config.voice.tts_engine = tts

    # Personality
    print("\nPersonality:")
    print("  Styles: casual (friend), professional (assistant), balanced (mix)")
    style = input(f"Style [{config.personality.style}]: ").strip()
    if style:
        config.personality.style = style

    # Claude Code
    claude_path = input(f"\nClaude Code CLI path [{config.claude_code_path}]: ").strip()
    if claude_path:
        config.claude_code_path = claude_path

    config.save()
    print(f"\nConfig saved to {EL_CONFIG_FILE}")
    print("Run 'el start' to launch EL!")


def cmd_config(args):
    """Show current config."""
    config = ELConfig.load()
    from dataclasses import asdict
    print(json.dumps(asdict(config), indent=2))


def cmd_status(args):
    """Show EL status."""
    import subprocess
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "el"],
        capture_output=True, text=True,
    )
    status = result.stdout.strip()
    if status == "active":
        print("EL is running.")
    else:
        print("EL is not running. Start with: el start")


def cmd_install_service(args):
    """Install EL as a systemd user service for always-on operation."""
    import shutil
    service_content = f"""[Unit]
Description=EL Personal AI Agent
After=network.target

[Service]
Type=simple
ExecStart={sys.executable} -m el.cli start
Restart=always
RestartSec=10
Environment=EL_HOME={EL_HOME}

[Install]
WantedBy=default.target
"""
    service_dir = EL_HOME.parent / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_file = service_dir / "el.service"
    service_file.write_text(service_content)
    print(f"Service installed: {service_file}")
    print("Enable with: systemctl --user enable el")
    print("Start with:  systemctl --user start el")
    print("Logs:        journalctl --user -u el -f")


def main():
    parser = argparse.ArgumentParser(
        prog="el",
        description="EL - Your Personal AI Agent",
    )
    subparsers = parser.add_subparsers(dest="command")

    # start
    start_parser = subparsers.add_parser("start", help="Start EL daemon")
    start_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    start_parser.set_defaults(func=cmd_start)

    # setup
    setup_parser = subparsers.add_parser("setup", help="Interactive setup")
    setup_parser.set_defaults(func=cmd_setup)

    # config
    config_parser = subparsers.add_parser("config", help="Show current config")
    config_parser.set_defaults(func=cmd_config)

    # status
    status_parser = subparsers.add_parser("status", help="Check if EL is running")
    status_parser.set_defaults(func=cmd_status)

    # install
    install_parser = subparsers.add_parser("install-service", help="Install as systemd service")
    install_parser.set_defaults(func=cmd_install_service)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
