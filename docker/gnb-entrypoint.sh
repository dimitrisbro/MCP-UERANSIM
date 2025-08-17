#!/bin/bash

# Replace values in the configuration file
sed -i "s/linkIp: .*/linkIp: $LINK_IP/" /etc/ueransim/open5gs-gnb.yaml
sed -i "s/ngapIp: .*/ngapIp: $NGAP_IP/" /etc/ueransim/open5gs-gnb.yaml
sed -i "s/gtpIp: .*/gtpIp: $GTP_IP/" /etc/ueransim/open5gs-gnb.yaml
sed -i "s/address: .*/address: $AMF_ADDRESS/" /etc/ueransim/open5gs-gnb.yaml
sed -i "s/port: .*/port: $AMF_PORT/" /etc/ueransim/open5gs-gnb.yaml

# Execute nr-gnb with the configured file
exec nr-gnb -c /etc/ueransim/open5gs-gnb.yaml