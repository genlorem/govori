# govori relay

FastAPI server running on VPS (Tailscale `100.121.161.56:8765`).
Receives voice audio from iPhone Shortcuts, transcribes via Whisper,
and optionally saves as a structured note to `~/life/notes/`.

## Deploy

1. SSH into VPS, clone govori if not already present (private repo — use SSH key):
   ```
   git clone git@github.com:<org>/govori.git ~/Projects/govori
   ```
2. Run the deploy script **on the VPS**:
   ```
   cd ~/Projects/govori && bash extras/install-vps.sh
   ```

## Local test (mac)

```bash
cd ~/Projects/govori
pip install fastapi uvicorn python-multipart
GOVORI_RELAY_HOST=127.0.0.1 uvicorn govori.server:app --port 8765 --reload
```

## Endpoints

| Method | Path    | Description                           |
|--------|---------|---------------------------------------|
| POST   | /note   | Transcribe + classify + save to notes |
| POST   | /dict   | Transcribe only, no save              |
| GET    | /health | Liveness check                        |

All POST endpoints accept `multipart/form-data` with field `audio`
(supported formats: .m4a, .mp3, .opus, .ogg, .wav, .aiff, .caf).

## iPhone Shortcut setup

1. Add action **Record Audio** — saves recording to a variable.
2. Add action **Get Contents of URL**:
   - URL: `http://100.121.161.56:8765/note`
   - Method: POST
   - Request body: Form (multipart)
   - Field name: `audio`, value: the recorded audio variable
3. Add action **Show Result** with `json['text']` from the response.

Use `/dict` instead of `/note` if you only want transcription without saving.

## Logs

```bash
tail -f ~/.config/govori/relay.log
```

## Service management

```bash
systemctl --user status govori-relay
systemctl --user restart govori-relay
systemctl --user stop govori-relay
```
