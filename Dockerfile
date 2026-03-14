FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Install Node.js 20 for the WhatsApp bridge and graph-ui-new build
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg git && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p fagent bridge && touch fagent/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf fagent bridge

# Build graph-ui-new (Next.js static export → out/)
# Separate layer so npm install is cached independently
COPY fagent/static/graph-ui-new/package.json fagent/static/graph-ui-new/package-lock.json /tmp/graph-ui-new/
WORKDIR /tmp/graph-ui-new
RUN npm install --legacy-peer-deps

COPY fagent/static/graph-ui-new/ /tmp/graph-ui-new/
RUN npm run build

# Copy the compiled static output into the source tree
RUN mkdir -p /app/fagent/static/graph-ui-new && \
    cp -r /tmp/graph-ui-new/out /app/fagent/static/graph-ui-new/out

WORKDIR /app

# Copy the full source and install
COPY fagent/ fagent/
COPY bridge/ bridge/
RUN uv pip install --system --no-cache .

# Build the WhatsApp bridge
WORKDIR /app/bridge
RUN npm install && npm run build
WORKDIR /app

# Create config directory
RUN mkdir -p /root/.fagent

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["fagent"]
CMD ["status"]
