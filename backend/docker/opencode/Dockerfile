# Thin OpenCode ACP runtime image. Build requires network access to download
# the official OpenCode CLI; credentials are injected at container creation.
FROM node:22-bookworm-slim
RUN npm install --global @opencode/cli@2.0.22
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin opencode \
    && mkdir -p /home/opencode/.config/opencode /home/opencode/.local/share/opencode /home/opencode/.local/state \
    && chown -R opencode:opencode /home/opencode/.config /home/opencode/.local
WORKDIR /workspace
ENTRYPOINT ["opencode"]
CMD ["acp"]
