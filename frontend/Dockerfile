# Kosmo frontend production image (used by docker-compose.prod.yml).
# Multi-stage: pnpm build, then nginx serves the static bundle and proxies
# /api (including SSE) to the backend service.

FROM node:24-alpine AS build
WORKDIR /app
RUN npm install --global pnpm@11.2.2
# pnpm 11 build-script policy lives in pnpm-workspace.yaml (allowBuilds);
# legacy knobs (onlyBuiltDependencies, npm_config_* env) are ignored by pnpm 11.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
