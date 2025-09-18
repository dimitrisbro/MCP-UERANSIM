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
RUN git clone https://github.com/aligungr/UERANSIM.git

# Compile UERANSIM
WORKDIR /opt/UERANSIM
RUN make

# Minimal runtime image with distroless-style approach
FROM ubuntu:22.04

# Install only runtime dependencies
RUN apt-get update && apt-get install -y \
    libsctp-dev \
    lksctp-tools \
    iproute2 \
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

# Default value για GNB_SEARCH_LIST
ENV GNB_SEARCH_LIST="127.0.0.1"

# Script for dynamic configuration (available for manual use)
COPY docker/ue-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/ue-entrypoint.sh

# Keep container alive but don't start UERANSIM automatically
# The MCP server will start it manually after configuration
CMD ["tail", "-f", "/dev/null"]
