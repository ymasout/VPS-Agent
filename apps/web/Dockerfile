FROM node:22-alpine AS build
ARG CONTROL_PLANE_VERSION=unset
ARG CONTROL_PLANE_COMMIT_SHA=unknown-build
ARG CONTROL_PLANE_BUILD_TIME=unknown-build-time
WORKDIR /repo
ENV DOCKER_BUILD=1 \
    CONTROL_PLANE_VERSION=${CONTROL_PLANE_VERSION} \
    CONTROL_PLANE_COMMIT_SHA=${CONTROL_PLANE_COMMIT_SHA} \
    CONTROL_PLANE_BUILD_TIME=${CONTROL_PLANE_BUILD_TIME}
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web apps/web
RUN pnpm --filter @vps-agent/web build

FROM node:22-alpine AS runtime
ARG CONTROL_PLANE_VERSION=unset
ARG CONTROL_PLANE_COMMIT_SHA=unknown-build
ARG CONTROL_PLANE_BUILD_TIME=unknown-build-time
WORKDIR /app
ENV NODE_ENV=production \
    CONTROL_PLANE_VERSION=${CONTROL_PLANE_VERSION} \
    CONTROL_PLANE_COMMIT_SHA=${CONTROL_PLANE_COMMIT_SHA} \
    CONTROL_PLANE_BUILD_TIME=${CONTROL_PLANE_BUILD_TIME}
LABEL org.opencontainers.image.version=${CONTROL_PLANE_VERSION} \
      org.opencontainers.image.revision=${CONTROL_PLANE_COMMIT_SHA} \
      org.opencontainers.image.created=${CONTROL_PLANE_BUILD_TIME}
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
