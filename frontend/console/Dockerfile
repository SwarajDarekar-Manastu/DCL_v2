# DCL Console: static SvelteKit build served by nginx (file 08 §7). S4 wires it into compose.
# VITE_* values are baked in at build time (src/lib/config.ts); none of them is a secret.

FROM node:24.13-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# The screenshots the in-app guides show live in the repository's asset/ folder (named build context `asset`,
# see backend/devops/compose.yaml); svelte.config.js aliases it as $asset (../../asset from /app).
COPY --from=asset . /asset
ARG VITE_API_BASE_URL=""
ARG VITE_AUTH_MODE="msal"
ARG VITE_ENTRA_TENANT_ID=""
ARG VITE_ENTRA_CLIENT_ID=""
ARG VITE_ENTRA_API_SCOPE=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_AUTH_MODE=$VITE_AUTH_MODE \
    VITE_ENTRA_TENANT_ID=$VITE_ENTRA_TENANT_ID \
    VITE_ENTRA_CLIENT_ID=$VITE_ENTRA_CLIENT_ID \
    VITE_ENTRA_API_SCOPE=$VITE_ENTRA_API_SCOPE
RUN npm run build

FROM nginx:1.29.3-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/healthz || exit 1
