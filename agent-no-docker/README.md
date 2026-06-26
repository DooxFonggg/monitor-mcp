# 🎛️ Hướng Dẫn Giám Sát Proxmox VE & Tường Lửa pfSense

Tài liệu này hướng dẫn thiết lập hệ thống giám sát độc lập cho **Proxmox VE** (cài đặt dạng Native không dùng Docker) và **Tường lửa pfSense**. 

Để tối ưu hóa luồng đi và đơn giản hóa kết nối, toàn bộ log và metrics của **pfSense** sẽ được **đẩy trực tiếp về Master Node** thay vì đi trung gian qua máy Proxmox.

---

## 🏛️ Dòng Chảy Dữ Liệu & Giao Thức (Data Flow & Protocols)

```
┌──────────────────────────────────┐        ┌──────────────────────────────────┐
│         pfSense Firewall         │        │          Proxmox VE Host         │
│  - Node Exporter (Metrics: 9100) │        │  - Grafana Alloy (Native Agent)  │
│  - Remote Syslog (Logs: UDP 1514)│        │  - Logs & Host Metrics           │
└────────────────┬─────────────────┘        └────────────────┬─────────────────┘
                 │                                           │
                 │                                           │
  Logs (UDP 1514)│                                           │ Push Metrics & Logs
  Metrics (9100) │                                           │ (Ports: 9090, 3100)
                 ▼                                           ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                                 Master Node                                  │
│       - Grafana Alloy: Lắng nghe Syslog ở cổng 1514 & Scrape Metrics cổng 9100│
│       - Prometheus: Lưu trữ metrics                                          │
│       - Loki: Lưu trữ log tập trung                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Phần 1: Cấu Hình trên Master Node (Nhận Logs/Metrics pfSense)

Để Master Node có thể nhận logs và metrics trực tiếp từ pfSense, ta thực hiện các bước sau ngay trên máy chủ **Master**:

### Bước 1.1: Khai báo IP pfSense
Mở file `.env` của thư mục `master/` và bổ sung thêm IP của pfSense:
```env
PFSENSE_IP=<IP_PFSENSE_CỦA_BẠN>
```

### Bước 1.2: Restart Master Services
Khởi động lại các container trên Master để kích hoạt mở cổng `1514` và cấu hình Alloy mới:
```bash
cd master
docker compose up -d --force-recreate alloy
```

---

## 🚀 Phần 2: Cài Đặt Giám Sát trên Proxmox VE (Debian)

Thực hiện các bước sau ngay trên shell của Proxmox VE:

### Bước 2.1: Sao chép thư mục cấu hình
Copy toàn bộ thư mục `agent-no-docker` này lên máy Proxmox VE (ví dụ: `/root/agent-no-docker`).

### Bước 2.2: Tạo file cấu hình `.env` trên Proxmox
```bash
cd /root/agent-no-docker
cp .env.example .env
```
Mở tệp `.env` và cập nhật thông tin IP:
```env
# IP của máy chủ Master chứa Prometheus/Loki
PROMETHEUS_URL=http://<IP_MASTER>:9090/api/v1/write
LOKI_URL=http://<IP_MASTER>:3100/loki/api/v1/push

# Thông tin của máy Proxmox VE này
AGENT_NAME=proxmox-ve
HOST_IP=<IP_PROXMOX>
```

### Bước 2.3: Chạy Script cài đặt tự động
```bash
chmod +x install.sh
sudo ./install.sh
```
Sau bước này, Proxmox VE sẽ tự động cài Alloy và đẩy các metrics, log hệ thống của chính nó về Master Node.

---

## 🛡️ Phần 3: Cấu Hình trên Tường Lửa pfSense

### 1. Cấu hình đẩy Logs (Remote Syslog)
1. Đăng nhập vào trang quản trị WebUI của pfSense.
2. Truy cập **Status** -> **System Logs** -> chọn tab **Settings**.
3. Cuộn xuống phần **Remote Log Options**:
   * Tích chọn **Send system logs to remote syslog server**.
   * **Source Address**: Chọn **WAN** (hoặc interface có định tuyến thông tới Master Node).
   * **IP Protocol**: `IPv4`.
   * **Remote Log Servers**: Điền **IP của Master Node** và cổng **`1514`** vào **ô đầu tiên** (ví dụ: `192.168.1.100:1514`). Đảm bảo không dùng ngoặc nhọn `< >` và xóa trống các ô còn lại.
   * **Remote Syslog Contents**: Tích chọn những loại log bạn muốn gửi về Loki (khuyên dùng: *Everything* hoặc chọn *System Events*, *Firewall Events*, *Routing Events*).
4. Nhấn **Save**.

### 2. Cấu hình thu thập Metrics (Node Exporter)
Bạn có thể thực hiện theo 1 trong 2 cách sau:

#### Cách A: Cấu hình qua giao diện WebUI (Khuyên dùng)
1. Trên pfSense WebUI, truy cập **System** -> **Package Manager** -> **Available Packages**.
2. Tìm kiếm gói `prometheus-node-exporter` và nhấn **Install**.
3. Sau khi cài đặt hoàn tất, truy cập **Services** -> **Prometheus Node Exporter**:
   * Tích chọn **Enable Prometheus Node Exporter**.
   * **Listen Address**: Chọn **WAN** (hoặc interface kết nối thông với Master Node).
   * **Listen Port**: Giữ mặc định `9100`.
4. Nhấn **Save**.

#### Cách B: Cấu hình qua Command Line (SSH)
1. Kết nối SSH tới pfSense (chọn mục `8) Shell` từ menu console trực tiếp).
2. Chạy các lệnh cài đặt và kích hoạt:
   ```bash
   pkg install -y pfSense-pkg-prometheus-node-exporter
   sysrc prometheus_node_exporter_enable="YES"
   service prometheus_node_exporter start
   ```

### 3. Cấu hình Luật Tường lửa (Firewall Rule) cho cổng WAN
Mặc định, pfSense sẽ chặn (Block) toàn bộ kết nối đi vào qua WAN. Bạn cần cho phép **Master Node** kết nối tới cổng `9100` của pfSense để lấy metrics:
1. Trên pfSense WebUI, truy cập **Firewall** -> **Rules** -> Chọn tab **WAN**.
2. Nhấn nút **Add** (Thêm rule mới lên đầu):
   * **Action**: `Pass` (Cho phép).
   * **Interface**: `WAN`.
   * **Address Family**: `IPv4`.
   * **Protocol**: `TCP`.
   * **Source**: `Single host or alias` -> Nhập **IP của Master Node** (ví dụ: `192.168.1.100`).
   * **Destination**: `WAN Address` (hoặc `Any`).
   * **Destination Port Range**: Custom -> Nhập `9100` vào cả hai ô *From* và *To*.
   * **Description**: `Allow Master Node to Scrape Node Exporter metrics`.
3. Nhấn **Save** và chọn **Apply Changes** ở thanh thông báo màu xanh phía trên cùng.

---

## 🔍 Kiểm tra hoạt động trên Grafana (Master)

Sau khi hoàn tất cấu hình, truy cập vào Grafana của bạn:

* **Log của pfSense (Loki):** `{job="pfsense-syslog"}`
* **Metrics của pfSense (Prometheus):** `node_cpu_seconds_total{instance="pfsense"}`
* **Log của Proxmox (Loki):** `{job="systemd", instance="proxmox-ve"}`
* **Metrics của Proxmox (Prometheus):** `node_cpu_seconds_total{instance="proxmox-ve"}`
