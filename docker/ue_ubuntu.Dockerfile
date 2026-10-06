# Multi-stage build with minimal Ubuntu
FROM ubuntu:22.04 AS builder

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies without snap
RUN apt-get update && apt-get install -y \
    nano \
    make \
    gcc \
    g++ \
    cmake \
    libsctp-dev \
    lksctp-tools \
    git \
    && rm -rf /var/lib/apt/lists/*

# Clone UERANSIM
WORKDIR /opt
# Pinned release tag: an unpinned clone takes whatever master is on each rebuild.
ARG UERANSIM_VERSION=v3.3.0
RUN git clone --depth 1 --branch ${UERANSIM_VERSION} https://github.com/aligungr/UERANSIM.git

# Compile UERANSIM
WORKDIR /opt/UERANSIM
RUN make

# Minimal runtime image with distroless-style approach
FROM ubuntu:22.04

# Install only runtime dependencies
# procps: provides pgrep (used by MCP server for process status checks)
# mawk:   provides awk  (used by MCP server for slice/config block rewrites)
RUN apt-get update && apt-get install -y \
    libsctp-dev \
    lksctp-tools \
    iproute2 \
    procps \
    mawk \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /usr/share/doc/* \
    && rm -rf /usr/share/man/* \
    && rm -rf /var/cache/debconf/* \
    && rm -rf /usr/share/locale/*

# Copy UE executable and configuration files
COPY --from=builder /opt/UERANSIM/build/nr-ue /usr/local/bin/
RUN mkdir -p /etc/ueransim

# Copy configuration file
COPY config/open5gs-ue.yaml /etc/ueransim/

# Label for container type identification
LABEL ueransim.type=ue

# Default values for environment variables
ENV GNB_SEARCH_LIST="127.0.0.1" \
    SUPI="" \
    MCC="999" \
    MNC="70" \
    KEY="" \
    OP="" \
    OP_TYPE="OPC" \
    SLICE_SST="1" \
    SLICE_SD="" \
    SESSION_APN="internet" \
    TUN_NETMASK="255.255.255.0"

# Script for dynamic configuration (available for manual use)
COPY docker/ue-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/ue-entrypoint.sh

# Keep container alive but don't start UERANSIM automatically
# The MCP server will start it manually after configuration
CMD ["tail", "-f", "/dev/null"]
