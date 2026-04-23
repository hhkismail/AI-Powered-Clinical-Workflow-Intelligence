import requests, os, base64
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ZAI_API_KEY")

def image_to_text(image_path: str) -> str:
    with open(image_path, "rb") as img_file:
        image_data = base64.b64encode(img_file.read()).decode("utf-8")

    ext = image_path.split(".")[-1].lower()
    mime_type = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"

    response = requests.post(
        "https://ocr.z.ai/v1/recognize",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "image": f"data:{mime_type};base64,{image_data}",
            "language": "en",
            "mode": "medical"
        }
    )

    if response.status_code == 200:
        return response.json().get("text", "")
    else:
        raise Exception(f"OCR failed: {response.status_code} - {response.text}")

if __name__ == "__main__":
    print(image_to_text("test_note.jpg"))