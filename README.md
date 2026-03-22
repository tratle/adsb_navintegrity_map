# ADS-B Navigation Integrity Map

This app shows flights from adsb.lol and adsb.one at selected locations.
Aircraft markers are color coded by ADS-B Navigation Integrity Category (NIC).

## Run Locally

1. Install dependencies:

	pip install -r requirements.txt

2. Start the app:

	python adsb_navintegrity_map.py

3. Open:

	http://localhost:8050

## Deploy To A Homelab With Docker

### Prerequisites

1. Docker Engine + Docker Compose plugin installed on your homelab host.
2. Port 8050 open on your LAN, or a reverse proxy in front.

### Quick Deploy

1. Clone this repo on your homelab host.
2. From the project folder, run:

	docker compose up -d --build

3. Confirm the container is healthy:

	docker compose ps

4. Open:

	http://<your-homelab-ip>:8050

### Update Later

Pull latest changes and redeploy:

docker compose up -d --build

### Logs And Troubleshooting

View logs:

docker compose logs -f

Stop service:

docker compose down

## Optional: Expose Through Reverse Proxy

If you already use Nginx Proxy Manager, Caddy, Traefik, or similar, route a domain/subdomain to:

- Upstream host: your Docker host
- Upstream port: 8050

That gives you cleaner URLs and easier TLS management.

## Files Added For Deployment

- Docker image definition: Dockerfile
- Compose service: docker-compose.yml
- Build context cleanup: .dockerignore
