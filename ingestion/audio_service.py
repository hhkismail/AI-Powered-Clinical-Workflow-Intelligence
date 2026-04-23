import requests, os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ZAI_API_KEY")

def audio_to_text(audio_path: str) -> str:
    with open(audio_path, "rb") as audio_file:
        response = requests.post(
            "https://audio.z.ai/v1/transcribe",
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"file": (os.path.basename(audio_path), audio_file, "audio/mpeg")},
            data={"language": "en", "domain": "medical"}
        )

    if response.status_code == 200:
        return response.json().get("transcript", "")
    else:
        raise Exception(f"Audio failed: {response.status_code} - {response.text}")

if __name__ == "__main__":
    print(audio_to_text("test_voice.mp3"))