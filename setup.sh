#!/usr/bin/env bash
set -euo pipefail

echo "========================================"
echo "  EL - Personal AI Agent Setup"
echo "========================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3.11+ required. Install it first."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python version: $PYTHON_VERSION"

# Check ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo ""
    echo "WARNING: ffmpeg not found. Voice messages won't work without it."
    echo "Install: sudo apt install ffmpeg  (or: brew install ffmpeg)"
    echo ""
fi

# Check Claude Code
if ! command -v claude &> /dev/null; then
    echo ""
    echo "WARNING: Claude Code CLI not found in PATH."
    echo "Install it from: https://docs.anthropic.com/en/docs/claude-code"
    echo ""
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# Install EL
echo "Installing EL..."
pip install -e .

# Ask about TTS engine
echo ""
echo "Which TTS engine do you want?"
echo "  1) Bark (most human-like voice, needs GPU with 4GB+ VRAM)"
echo "  2) Piper (lighter, runs on CPU)"
echo "  3) Skip for now"
read -p "Choice [1/2/3]: " tts_choice

case $tts_choice in
    1) pip install bark ;;
    2) pip install piper-tts ;;
    3) echo "Skipping TTS install." ;;
    *) echo "Skipping TTS install." ;;
esac

echo ""
echo "========================================"
echo "  EL installed successfully!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Run: el setup"
echo "     (Configure Telegram bot token and preferences)"
echo ""
echo "  2. Run: el start"
echo "     (Launch EL)"
echo ""
echo "  3. Optional - Run 24/7:"
echo "     el install-service"
echo "     systemctl --user enable el"
echo "     systemctl --user start el"
echo ""
echo "  To get a Telegram bot token:"
echo "    - Open Telegram, search @BotFather"
echo "    - Send /newbot and follow the prompts"
echo "    - Copy the token it gives you"
echo ""
