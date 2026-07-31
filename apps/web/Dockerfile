ARG NODE_BASE_IMAGE=docker.io/library/node@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32
FROM ${NODE_BASE_IMAGE} AS build
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

FROM ${NODE_BASE_IMAGE} AS runtime
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
      org.opencontainers.image.created=${CONTROL_PLANE_BUILD_TIME} \
      org.opencontainers.image.source=https://github.com/ymasout/VPS-Agent \
      org.opencontainers.image.licenses=AGPL-3.0-only
COPY --chown=node:node --from=build /repo/apps/web/.next/standalone ./
COPY --chown=node:node --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --chown=node:node --from=build /repo/apps/web/public ./apps/web/public
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["node", "-e", "fetch('http://127.0.0.1:3000/manifest.webmanifest').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]
CMD ["node", "apps/web/server.js"]
