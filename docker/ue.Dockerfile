# Ubuntu base as recommended by UERANSIM official installation guide
FROM ubuntu:22.04 AS builder

# Install required dependencies following official guide
RUN apt-get update && apt-get install -y \
    make \
    gcc \
    g++ \
    libsctp-dev \
    lksctp-tools \
    iproute2 \
    git \
    && snap install cmake --classic \
    && rm -rf /var/lib/apt/lists/*

# Clone UERANSIM
WORKDIR /opt
RUN git clone https://github.com/aligungr/UERANSIM.git
WORKDIR /opt/UERANSIM

# Compile UERANSIM
RUN make

# Runtime image - minimal Ubuntu
FROM ubuntu:22.04

# Install runtime dependencies only
RUN apt-get update && apt-get install -y \
    libsctp-dev \
    lksctp-tools \
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Copy executables and configuration files
COPY --from=builder /opt/UERANSIM/build/nr-ue /usr/local/bin/
RUN mkdir -p /etc/ueransim
COPY config/open5gs-ue.yaml /etc/ueransim/

# Label for container type identification
LABEL ueransim.type=ue

# Default value for GNB_SEARCH_LIST
ENV GNB_SEARCH_LIST="127.0.0.1"

# Script for dynamic config configuration
COPY docker/ue-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/ue-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/ue-entrypoint.sh"]