# Try minimal installation with Alpine (as per instructions)
# If this fails to build, switch to Ubuntu base:
# Try Alpine first (minimal), fallback to Ubuntu if issues
# Uncomment the Alpine version below and comment Ubuntu if you want to test Alpine
# FROM alpine:3.19 AS builder

# Ubuntu base as recommended by UERANSIM official installation guide (CURRENT CHOICE)
FROM ubuntu:22.04 AS builder


# Install required dependencies for Alpine
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
COPY --from=builder /opt/UERANSIM/build/nr-gnb /usr/local/bin/
RUN mkdir -p /etc/ueransim

RUN mkdir -p /etc/ueransim
COPY config/open5gs-gnb.yaml /etc/ueransim/

# Label for container type identification
LABEL ueransim.type=gnb

# Default values for arguments
ENV LINK_IP="127.0.0.1" \
    NGAP_IP="127.0.0.1" \
    GTP_IP="127.0.0.1" \
    AMF_ADDRESS="127.0.0.5" \
    AMF_PORT="38412"

# Script for dynamic config configuration
COPY docker/gnb-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/gnb-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/gnb-entrypoint.sh"]

# ALTERNATIVE: Alpine-based version (uncomment to use)
# Replace the Ubuntu sections above with these if you want to try Alpine:
#
# FROM alpine:3.19 AS builder
# RUN apk add --no-cache \
#     build-base \
#     cmake \
#     make \
#     gcc \
#     g++ \
#     git \
#     linux-headers \
#     lksctp-tools-dev \
#     lksctp-tools
# WORKDIR /opt
# RUN git clone https://github.com/aligungr/UERANSIM.git
# WORKDIR /opt/UERANSIM
# RUN make
#
# FROM alpine:3.19
# RUN apk add --no-cache \
#     lksctp-tools \
#     libstdc++ \
#     bash
# COPY --from=builder /opt/UERANSIM/build/nr-gnb /usr/local/bin/
# RUN mkdir -p /etc/ueransim
# COPY config/open5gs-gnb.yaml /etc/ueransim/
# ... (rest same as Ubuntu version)