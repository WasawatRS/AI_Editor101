import os

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(os.path.join(BASE_DIR, ".env"))

REQUIRED_KEYS = ["GEMINI_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"]

INPUT_DIR = os.path.join(BASE_DIR, "input_videos")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def validate_config() -> None:
    missing = [k for k in REQUIRED_KEYS if not os.getenv(k, "").strip()]
    if missing:
        raise RuntimeError(
            "Missing required API keys in .env: " + ", ".join(missing)
            + " | Please add them to the file: "
            + os.path.join(BASE_DIR, ".env")
        )


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
ELEVENLABS_MODEL_ID = os.getenv("ELEVENLABS_MODEL_ID", "").strip() or "eleven_multilingual_v2"
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "").strip() or "gemini-3.8-flash"
