# Build: kompilasi backend + admin dashboard ke .medusa/server
FROM node:22.23.3-alpine3.24 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npx medusa build

# Runtime: hanya hasil build + dependensi produksi, dijalankan sebagai user node
FROM node:22.23.3-alpine3.24
ENV NODE_ENV=production
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
WORKDIR /server
RUN chown node:node /server
USER node
COPY --from=build --chown=node:node /app/.medusa/server ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force
EXPOSE 9000
ENTRYPOINT ["docker-entrypoint.sh"]
