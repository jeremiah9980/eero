# eero Network Intelligence

A cloud/API-oriented eero network presence intelligence app.

## Features

- Live device presence tracking
- Enter/leave notifications
- Automatic discovery of new devices
- Historical SQLite database
- Interactive web dashboard
- REST API endpoints
- WebSocket live updates
- Slack / Discord / Teams / Pushcut webhook notifications
- Docker Compose deployment
- Cloudflare Tunnel friendly
- Multi-network ready configuration
- DSAR import support for your eero personal data export

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml
mkdir -p data
python -m app.main --config config/config.yaml --import-dsar data/personal_data.zip
python -m app.main --config config/config.yaml --run
```

Open:

```text
http://localhost:8080
```

## Docker

```bash
cp config/config.example.yaml config/config.yaml
docker compose up --build -d
```

## Cloudflare Tunnel

Install `cloudflared`, then run:

```bash
cloudflared tunnel --url http://localhost:8080
```

Or add this app behind an existing named tunnel.

## Security notes

Do not commit:

- `config/config.yaml`
- session cookies
- DSAR exports
- SQLite database files
- webhook URLs

This project intentionally ships only with `config.example.yaml`.

## API

```text
GET /api/health
GET /api/devices
GET /api/events
GET /api/networks
WS  /ws
```

## Presence strategy

The best identifier order is:

1. eero device/client ID
2. MAC address
3. stable hostname/nickname

Names like `iPhone` are ambiguous, so import DSAR data first when possible.
