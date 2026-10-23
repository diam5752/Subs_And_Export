# Base stage (Dependencies)
FROM node:26-alpine AS deps
WORKDIR /app

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Builder stage
FROM node:26-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time env vars
ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ARG NEXT_PUBLIC_MAX_UPLOAD_MB=500
ARG NEXT_PUBLIC_MAX_VIDEO_DURATION_SECONDS=180
ARG NEXT_PUBLIC_TRANSCRIBE_PROVIDER=mock
ARG NEXT_PUBLIC_TRANSCRIBE_MODE=standard
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_MAX_UPLOAD_MB=${NEXT_PUBLIC_MAX_UPLOAD_MB}
ENV NEXT_PUBLIC_MAX_VIDEO_DURATION_SECONDS=${NEXT_PUBLIC_MAX_VIDEO_DURATION_SECONDS}
ENV NEXT_PUBLIC_TRANSCRIBE_PROVIDER=${NEXT_PUBLIC_TRANSCRIBE_PROVIDER}
ENV NEXT_PUBLIC_TRANSCRIBE_MODE=${NEXT_PUBLIC_TRANSCRIBE_MODE}

RUN npm run build

# ============================================
# Production stage
FROM node:26-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV APP_ENV=production

# Apply available Alpine security fixes and remove build/package-management
# tooling from the runtime image. The standalone Next.js server needs Node,
# but not npm, npx, Corepack, or Yarn.
RUN apk upgrade --no-cache \
    && rm -rf /usr/local/lib/node_modules/npm \
        /usr/local/lib/node_modules/corepack \
        /opt/yarn-v* \
    && rm -f /usr/local/bin/npm \
        /usr/local/bin/npx \
        /usr/local/bin/corepack \
        /usr/local/bin/yarn \
        /usr/local/bin/yarnpkg

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Copy standalone output
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000 || exit 1

EXPOSE 3000

CMD ["node", "server.js"]
