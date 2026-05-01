#!/bin/bash
# Run ONCE after first deploy to issue the SSL certificate.
# Run from /opt/wattlelink on the server.
# Your DNS A record must already be pointing to this server's IP.
set -e

DOMAIN="wattlelink.com.au"
EMAIL="chris.bush646@gmail.com"
COMPOSE="docker compose -f docker-compose.prod.yml"

echo "=== Step 1: Create dummy certificate so Nginx can start ==="
mkdir -p ./certbot/conf/live/$DOMAIN
openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
  -keyout ./certbot/conf/live/$DOMAIN/privkey.pem \
  -out    ./certbot/conf/live/$DOMAIN/fullchain.pem \
  -subj   "/CN=localhost" 2>/dev/null

echo "=== Step 2: Start Nginx with dummy cert ==="
$COMPOSE up -d nginx

echo "=== Step 3: Remove dummy cert ==="
rm -rf ./certbot/conf/live/$DOMAIN

echo "=== Step 4: Issue real certificate from Let's Encrypt ==="
$COMPOSE run --rm certbot certonly \
  --webroot \
  --webroot-path=/var/www/certbot \
  --email "$EMAIL" \
  --agree-tos \
  --no-eff-email \
  -d "$DOMAIN" \
  -d "www.$DOMAIN"

echo "=== Step 5: Reload Nginx with real cert ==="
$COMPOSE exec nginx nginx -s reload

echo "=== Step 6: Start remaining services ==="
$COMPOSE up -d

echo ""
echo "Done! https://www.$DOMAIN is live."
echo "Certificates auto-renew every 12 hours via the certbot container."
