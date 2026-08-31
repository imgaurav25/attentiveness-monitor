# Frontend production image: builds the React app, then serves the static
# files AND reverse-proxies /api + /ws to the backend, all from Caddy
# (which also handles automatic HTTPS via Let's Encrypt when given a real
# domain in DOMAIN).
#
# Build from the frontend/ directory:
#   docker build -t attentiveness-frontend .
# (docker-compose.yml already does this correctly.)

# ---- Stage 1: build the React app ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

# ---- Stage 2: serve it with Caddy ----
FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
