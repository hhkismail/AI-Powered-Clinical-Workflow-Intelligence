# Clinical Notes Automation System - Mock Hospital Backend

This repository contains the Flask + Supabase backend used by the UI and orchestration teams.

## Handover Steps

1. Pull the repository.
2. Create your own `.env` file in the project root.
3. Ask Rizwi for the Supabase keys and add them to `.env`:
   - `SUPABASE_URL=...`
   - `SUPABASE_KEY=...`
4. Install dependencies from `requirements.txt`:
   ```powershell
   pip install -r requirements.txt
   ```
5. Start the backend server:
   ```powershell
   python server.py
   ```
6. Start the ngrok tunnel (choose one based on your shell):
   ```powershell
   ngrok http 3000
   ```
   or in PowerShell with local binary:
   ```powershell
   .\\ngrok http 3000
   ```
7. Send your new ngrok URL to the UI team.

## Notes

- Do not commit `.env` to GitHub.
- If dependencies change, regenerate `requirements.txt` and commit it.
# umhackathon2026-clinical
