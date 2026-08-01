FROM node:22-alpine AS deps

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

FROM node:22-alpine AS build

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime

WORKDIR /app
ENV NODE_ENV=production
# The standalone server binds to this address. Without it Next.js listens on
# localhost only, which resolves to ::1 inside the container and makes both the
# healthcheck and cross-container requests fail with connection refused.
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

# `output: "standalone"` emits a self-contained server plus a trimmed
# node_modules, so the runtime image stays small.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

USER node

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD wget -qO- http://127.0.0.1:3000/health > /dev/null || exit 1

CMD ["node", "server.js"]
