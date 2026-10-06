# Multi-stage build with minimal Ubuntu
FROM ubuntu:22.04 AS builder

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
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

# Copy executables and configuration files
COPY --from=builder /opt/UERANSIM/build/nr-gnb /usr/local/bin/
RUN mkdir -p /etc/ueransim

# Copy configuration file
COPY config/open5gs-gnb.yaml /etc/ueransim/

# Label for container type identification
LABEL ueransim.type=gnb

# Default values for environment variables
ENV LINK_IP="127.0.0.1" \
    NGAP_IP="127.0.0.1" \
    GTP_IP="127.0.0.1" \
    AMF_ADDRESS="127.0.0.5" \
    AMF_PORT="38412" \
    MCC="999" \
    MNC="70" \
    TAC="1" \
    SLICE_SST="1" \
    SLICE_SD="" \
    CELL_ACCESS_TYPE="nr" \
    IGNORE_STREAM_IDS="true"

# Script for dynamic configuration (available for manual use)
COPY docker/gnb-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/gnb-entrypoint.sh

# Keep container alive but don't start UERANSIM automatically
# The MCP server will start it manually after configuration
CMD ["tail", "-f", "/dev/null"]