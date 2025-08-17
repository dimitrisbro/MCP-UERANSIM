#!/bin/bash

# Replace value in the configuration file
sed -i "s/gnbSearchList: .*/gnbSearchList: $GNB_SEARCH_LIST/" /etc/ueransim/open5gs-ue.yaml

# Execute nr-ue with the configured file
exec nr-ue -c /etc/ueransim/open5gs-ue.yaml