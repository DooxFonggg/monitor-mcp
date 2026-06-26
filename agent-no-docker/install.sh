#!/usr/bin/env bash

# GRAFANA ALLOY INSTALLATION SCRIPT FOR DEBIAN / PROXMOX VE
# (Runs natively as a systemd service)

set -e

# ANSI Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=====================================================${NC}"
echo -e "${GREEN}   GRAFANA ALLOY INSTALLATION ON PROXMOX VE (DEBIAN)   ${NC}"
echo -e "${GREEN}=====================================================${NC}"

# Check if script is run as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Lỗi: Script này cần được chạy với quyền root (sudo).${NC}"
  exit 1
fi

# 1. Check if .env file exists
if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    echo -e "${YELLOW}Không tìm thấy file .env. Đang sao chép từ .env.example...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}Vui lòng chỉnh sửa file .env trước khi chạy lại script.${NC}"
    exit 0
  else
    echo -e "${RED}Lỗi: Không tìm thấy file .env hoặc .env.example!${NC}"
    exit 1
  fi
fi

# 2. Add Grafana Repository and GPG key
echo -e "${GREEN}[1/5] Thêm kho lưu trữ Grafana APT và GPG Key...${NC}"
apt-get update -y && apt-get install -y wget gpg software-properties-common apt-transport-https

mkdir -p /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/grafana.gpg ]; then
  wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | tee /etc/apt/keyrings/grafana.gpg > /dev/null
fi

echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | tee /etc/apt/sources.list.d/grafana.list

# 3. Update APT & Install Grafana Alloy
echo -e "${GREEN}[2/5] Đang cập nhật APT và cài đặt Grafana Alloy...${NC}"
apt-get update -y
apt-get install -y alloy

# Add alloy user to necessary groups to read journal & metrics
echo -e "${GREEN}[3/5] Phân quyền cho user 'alloy'...${NC}"
usermod -aG adm,systemd-journal alloy || true

# 4. Copy config.alloy
echo -e "${GREEN}[4/5] Sao chép tệp cấu hình config.alloy...${NC}"
mkdir -p /etc/alloy
cp config.alloy /etc/alloy/config.alloy
chown -R alloy:alloy /etc/alloy

# 5. Populate environment variables in /etc/default/alloy
echo -e "${GREEN}[5/5] Cập nhật các biến môi trường vào /etc/default/alloy...${NC}"

# Read .env file and write to /etc/default/alloy
ENV_DEFAULTS="/etc/default/alloy"

# Backup existing default configuration
if [ ! -f "${ENV_DEFAULTS}.bak" ]; then
  cp "$ENV_DEFAULTS" "${ENV_DEFAULTS}.bak"
fi

# Clean up previously appended custom vars to prevent duplication
sed -i '/# === CUSTOM ALLOY ENV VARS ===/,/# === END CUSTOM ALLOY ENV VARS ===/d' "$ENV_DEFAULTS"

echo -e "\n# === CUSTOM ALLOY ENV VARS ===" >> "$ENV_DEFAULTS"
while IFS= read -r line || [ -n "$line" ]; do
  # Ignore comments and empty lines
  if [[ ! "$line" =~ ^# ]] && [[ ! -z "$line" ]]; then
    echo "$line" >> "$ENV_DEFAULTS"
    # Export it for immediate session if needed
    eval export "$line"
  fi
done < .env
echo "# === END CUSTOM ALLOY ENV VARS ===" >> "$ENV_DEFAULTS"

# 6. Restart & Enable Grafana Alloy Service
echo -e "${GREEN}Đang kích hoạt và khởi chạy dịch vụ Grafana Alloy...${NC}"
systemctl daemon-reload
systemctl enable alloy
systemctl restart alloy

# Check status
if systemctl is-active --quiet alloy; then
  echo -e "${GREEN}=====================================================${NC}"
  echo -e "${GREEN}✔ Cài đặt và cấu hình Grafana Alloy THÀNH CÔNG!${NC}"
  echo -e "${GREEN}✔ Trạng thái dịch vụ: RUNNING${NC}"
  echo -e "${GREEN}=====================================================${NC}"
  echo -e "IP pfSense đã cấu hình: ${YELLOW}${PFSENSE_IP}${NC}"
  echo -e "Hãy cấu hình pfSense gửi Remote Syslog về cổng ${YELLOW}${HOST_IP}:1514 (UDP hoặc TCP)${NC}"
else
  echo -e "${RED}Lỗi: Grafana Alloy không thể khởi động thành công. Vui lòng kiểm tra bằng lệnh: journalctl -u alloy -f${NC}"
  exit 1
fi
