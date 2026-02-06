"""EL Configuration and Settings."""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict


EL_HOME = Path(os.environ.get("EL_HOME", Path.home() / ".el"))
EL_CONFIG_FILE = EL_HOME / "config.json"
EL_DB_PATH = EL_HOME / "memory.db"
EL_VOICE_CACHE = EL_HOME / "voice_cache"
EL_LOGS = EL_HOME / "logs"


@dataclass
class TelegramConfig:
    bot_token: str = ""
    allowed_user_ids: list[int] = field(default_factory=list)
    voice_enabled: bool = True


@dataclass
class VoiceConfig:
    stt_model: str = "base"  # whisper model: tiny, base, small, medium, large
    tts_engine: str = "bark"  # bark or piper
    bark_speaker: str = "v2/en_speaker_6"  # EL's unique voice
    sample_rate: int = 24000


@dataclass
class PersonalityConfig:
    name: str = "EL"
    style: str = "casual"  # casual, professional, balanced
    verbose: bool = False
    use_slang: bool = True
    remember_context: bool = True


@dataclass
class SchedulerConfig:
    enabled: bool = True
    check_interval_minutes: int = 5


@dataclass
class AgentConfig:
    max_concurrent_agents: int = 3
    timeout_seconds: int = 300


@dataclass
class ELConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    personality: PersonalityConfig = field(default_factory=PersonalityConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)
    claude_code_path: str = "claude"  # path to claude code CLI

    def save(self):
        EL_HOME.mkdir(parents=True, exist_ok=True)
        with open(EL_CONFIG_FILE, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls) -> "ELConfig":
        if EL_CONFIG_FILE.exists():
            with open(EL_CONFIG_FILE) as f:
                data = json.load(f)
            return cls(
                telegram=TelegramConfig(**data.get("telegram", {})),
                voice=VoiceConfig(**data.get("voice", {})),
                personality=PersonalityConfig(**data.get("personality", {})),
                scheduler=SchedulerConfig(**data.get("scheduler", {})),
                agents=AgentConfig(**data.get("agents", {})),
                claude_code_path=data.get("claude_code_path", "claude"),
            )
        config = cls()
        config.save()
        return config


def ensure_dirs():
    for d in [EL_HOME, EL_VOICE_CACHE, EL_LOGS]:
        d.mkdir(parents=True, exist_ok=True)
