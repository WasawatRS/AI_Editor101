import base64
import json

from elevenlabs.client import ElevenLabs

import config


def generate_speech_with_timestamps(text: str, output_audio_path: str,
                                    voice_id: str | None = None,
                                    model_id: str | None = None) -> dict:
    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

    response = client.text_to_speech.convert_with_timestamps(
        voice_id=voice_id or config.ELEVENLABS_VOICE_ID,
        model_id=model_id or config.ELEVENLABS_MODEL_ID,
        text=text,
        output_format="mp3_44100_128",
    )

    audio = _extract_audio(response)
    with open(output_audio_path, "wb") as f:
        f.write(audio)

    alignment = _normalize_alignment(response)
    duration = max(alignment["ends"]) if alignment["ends"] else 0.0

    with open(output_audio_path + ".align.json", "w", encoding="utf-8") as f:
        json.dump(alignment, f, ensure_ascii=False)

    return {
        "audio_path": output_audio_path,
        "duration_seconds": round(duration, 3),
        "alignment": alignment,
    }


def _extract_audio(response) -> bytes:
    audio = getattr(response, "audio_base_64", None) \
        or getattr(response, "audio_base64", None)
    if audio is not None:
        return base64.b64decode(audio)
    if isinstance(response, (bytes, bytearray)):
        return bytes(response)
    raise TypeError(
        "Unknown audio return format from convert_with_timestamps: {}".format(type(response))
    )


def _normalize_alignment(response) -> dict:
    alignment = getattr(response, "alignment", None)
    if alignment is None:
        alignment = response if isinstance(response, dict) else {}
    return {
        "characters": list(alignment.get("characters", []
                        ) if isinstance(alignment, dict) else alignment.characters),
        "starts": list(alignment.get("character_start_times_seconds", [])
                       if isinstance(alignment, dict)
                       else alignment.character_start_times_seconds),
        "ends": list(alignment.get("character_end_times_seconds", [])
                     if isinstance(alignment, dict)
                     else alignment.character_end_times_seconds),
    }
