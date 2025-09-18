# Alpine Linux base
FROM alpine:3.16 AS builder

# Install required dependencies
RUN apk add --no-cache \
    gcc g++ cmake ninja make nano iproute2 \
    libc-dev linux-headers git \
    lksctp-tools-dev lksctp-tools \
    musl-dev

# Clone UERANSIM
WORKDIR /opt
RUN git clone https://github.com/aligungr/UERANSIM.git
WORKDIR /opt/UERANSIM

# Build UERANSIM
RUN make

# Final image
FROM alpine:3.16

# Install required runtime libraries
RUN apk add --no-cache \
    nano \
    iproute2 \
    lksctp-tools \
    libstdc++ \
    bash

# Copy executables and configuration files
COPY --from=builder /opt/UERANSIM/build/nr-ue /usr/local/bin/
RUN mkdir -p /etc/ueransim

# Copy configuration file
COPY config/open5gs-ue.yaml /etc/ueransim/

# Label for container type identification
LABEL ueransim.type=ue

# Default value for GNB_SEARCH_LIST
ENV GNB_SEARCH_LIST="127.0.0.1"

# Script for dynamic configuration
COPY docker/ue-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/ue-entrypoint.sh

# Keep container running without starting UERANSIM automatically
CMD ["tail", "-f", "/dev/null"]