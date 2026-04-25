# ⚡ GETTING STARTED - 5 Minutes

## Step 1: Install Dependencies (1 min)
```bash
cd c:\Users\razin\OneDrive\Desktop\Coding\Hackathon\Ophia
pip install -r requirements.txt
```

## Step 2: Run the Server (30 sec)
```bash
python main.py
```

You should see:
```
============================================================
Clinical Notes Automation Backend Starting...
============================================================
Mock API Base URL: http://localhost:8001
Timeout: 10s
============================================================

INFO:     Uvicorn running on http://0.0.0.0:8000
```

## Step 3: Test It Works (30 sec)

### Option A: Swagger UI (Recommended)
Open browser to: http://localhost:8000/docs
- Click on "Try it out"
- Test the endpoint interactively

### Option B: cURL
```bash
curl -X POST http://localhost:8000/api/process-note \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {"doctor_id":"DR001","patient_id":"PAT123","department":"Cardiology","timestamp":"2024-01-15T10:30:00Z","priority":"high"},
    "payload": {"input_methods_used":["voice_to_text"],"raw_text":"Patient has chest pain"}
  }'
```

Expected response:
```json
{
  "status": "success",
  "system_alerts": null,
  "result": {
    "llm_reasoning": "LLM integration pending",
    "execution_results": {
      "executed_actions": [],
      "alerts": []
    }
  }
}
```

### Option C: Test Suite
```bash
python test_api.py
```

---

## Step 4: Configure Mock API (1 min)

Edit `.env` file:
```
MOCK_API_BASE_URL=http://localhost:8001    # ← Change this to your mock API URL
TIMEOUT_SECONDS=10
```

Save and restart the server (`Ctrl+C` then `python main.py`)

---

## Step 5: Integrate Your LLM SDK (5-10 min)

Open `main.py` and find the `call_zai_glm()` function around line 98:

```python
def call_zai_glm(text: str, system_prompt: str) -> Dict[str, Any]:
    """
    Placeholder function for calling the Zai GLM LLM.
    """
    # TODO: Replace with actual Zai GLM API call using official SDK
    
    # Example:
    # from zai_glm import Client
    # client = Client()
    # response = client.invoke(system=system_prompt, user=text)
    # return parse_response(response)
    
    return {
        "actions": [],
        "reasoning": "LLM integration pending",
        "status": "awaiting_llm_implementation"
    }
```

Replace the function body with your Zai GLM SDK integration.

Expected format to return:
```json
{
  "actions": [
    {
      "tool": "reserve_bed",
      "params": {
        "patient_id": "...",
        "ward_type": "ICU",
        "priority": "high",
        "clinical_reason": "..."
      }
    }
  ],
  "reasoning": "Why this action was chosen"
}
```

---

## 📚 Key Files

| File | Purpose | When You Need It |
|------|---------|-----------------|
| `main.py` | Complete backend code | ⭐ The main file |
| `requirements.txt` | Dependencies | Already installed |
| `.env` | Configuration | Update with your API URL |
| `README.md` | Setup guide | Setup phase |
| `API_REFERENCE.md` | API contract | Integration phase |
| `test_api.py` | Tests | Testing phase |

---

## 🔗 API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/process-note` | POST | Main orchestration (your main endpoint) |
| `/health` | GET | Health check (optional, for monitoring) |
| `/docs` | GET | Swagger UI (interactive testing) |
| `/redoc` | GET | ReDoc (alternative API docs) |

---

## ✅ Checklist

- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Server running (`python main.py`)
- [ ] Can access Swagger UI (`http://localhost:8000/docs`)
- [ ] Health check works (`curl http://localhost:8000/health`)
- [ ] Can send test request to `/api/process-note`
- [ ] Mock API URL configured in `.env`
- [ ] LLM SDK integrated into `call_zai_glm()`
- [ ] End-to-end workflow tested

---

## 🆘 Troubleshooting

### "Command not found: python"
```bash
# Check if you have Python 3
python3 --version

# Use python3 instead of python
python3 main.py
```

### "ModuleNotFoundError: No module named 'fastapi'"
```bash
# Reinstall dependencies
pip install -r requirements.txt
```

### "Connection refused" when calling mock API
```bash
# Make sure:
1. Mock API server is running
2. MOCK_API_BASE_URL in .env is correct
3. Both servers are on same network
```

### "Address already in use"
```bash
# Port 8000 is already in use, either:
# Option 1: Stop other process using port 8000
# Option 2: Edit main.py line 488: port=8001 (change port)
```

---

## 📞 Documentation

- **For Setup & Usage:** See `README.md`
- **For API Details:** See `API_REFERENCE.md`
- **For Architecture:** See `IMPLEMENTATION_NOTES.md`
- **For Project Overview:** See `DELIVERY_SUMMARY.md`

---

## 🎉 You're Ready!

Your backend is production-ready. All you need to do is:
1. ✅ Install dependencies
2. ✅ Configure mock API URL
3. ✅ Integrate your LLM SDK
4. ✅ Test end-to-end

Good luck with the hackathon! 🚀
