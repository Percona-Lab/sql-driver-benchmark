#!/bin/bash
# 24.04 -> 26.04 in-place LTS upgrade (Vultr has no 26.04 image for this plan)
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get -y -o Dpkg::Options::=--force-confold dist-upgrade
apt-get -y install update-manager-core
sed -i 's/^Prompt=.*/Prompt=lts/' /etc/update-manager/release-upgrades
do-release-upgrade -f DistUpgradeViewNonInteractive || do-release-upgrade -d -f DistUpgradeViewNonInteractive
