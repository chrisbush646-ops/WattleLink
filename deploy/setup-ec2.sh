#!/bin/bash
# Run this ONCE on a fresh Ubuntu 22.04 EC2 instance.
# ssh ubuntu@YOUR_SERVER_IP 'bash -s' < deploy/setup-ec2.sh
set -e

echo "=== Installing Docker ==="
apt-get update -q
apt-get install -y -q ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin

systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu

echo "=== Installing git ==="
apt-get install -y -q git

echo "=== Creating app directory ==="
mkdir -p /opt/wattlelink
chown ubuntu:ubuntu /opt/wattlelink

echo "=== Done. Log out and back in for docker group to take effect. ==="
echo "Next: upload your code to /opt/wattlelink and run deploy/init-letsencrypt.sh"
