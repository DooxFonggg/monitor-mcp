# 📊 Báo cáo Giám sát Tài nguyên & Hệ thống: `timescaledb-01`

Báo cáo này tổng hợp dữ liệu metrics và phân tích log thu thập được từ máy chủ client **`timescaledb-01`** (IP: `10.10.10.10`) nhằm đánh giá hiệu năng hệ thống và chẩn đoán sự cố kết nối.

---

## 🖥️ 1. Thông tin cấu hình & Trạng thái tải của Host

Dưới đây là các thông số tài nguyên hệ thống hiện tại của máy chủ `timescaledb-01` lấy từ Prometheus:

| Thông số | Giá trị | Chi tiết |
| :--- | :---: | :--- |
| **IP máy chủ (Host IP)** | `10.10.10.10` | Địa chỉ IP của client |
| **Số nhân CPU (CPU Cores)** | `1` Core | Hệ thống chạy trên 1 nhân CPU ảo hóa |
| **Thời gian hoạt động (Uptime)** | `8 giờ 41 phút` | Node exporter bắt đầu chạy được 31,315 giây |
| **Tải CPU hiện tại (CPU Usage)** | **`2.53%`** | Tải CPU ở mức rất thấp, hệ thống rảnh rỗi |
| **Bộ nhớ RAM (RAM Usage)** | **`30.27%`** | Tổng: `1.91 GB` \| Còn trống: `1.33 GB` \| Đang dùng: `594.4 MB` |
| **Dung lượng Đĩa (Disk Usage)** | **`20.07%`** | Tổng ổ `/`: `60.72 GB` \| Còn trống: `48.53 GB` \| Đang dùng: `12.18 GB` |

---

## 📋 2. Phân tích Nhật ký Log & Các Sự cố Phát hiện

Qua việc truy vấn dữ liệu Loki, máy chủ `timescaledb-01` hiện chỉ thu thập được log của 2 container giám sát chính là **`alloy`** và **`cadvisor`**. Phân tích cụ thể:

### 🔴 Sự cố 1: Grafana Alloy không đẩy được dữ liệu về Master Node
Trong log của container `alloy` liên tục xuất hiện cảnh báo kết nối bị từ chối từ phía Master Node (`10.10.10.7`):
* **Cảnh báo lỗi đẩy Logs (Loki)**:
  ```log
  level=warn msg="error sending batch, will retry" component_id=loki.write.loki_master host=10.10.10.7:3100 error="Post \"http://10.10.10.7:3100/loki/api/v1/push\": dial tcp 10.10.10.7:3100: connect: connection refused"
  ```
* **Cảnh báo lỗi đẩy Metrics (Prometheus)**:
  ```log
  level=warn msg="Failed to send batch, retrying" component_id=prometheus.remote_write.prometheus_master url=http://10.10.10.7:9090/api/v1/write err="Post \"http://10.10.10.7:9090/api/v1/write\": dial tcp 10.10.10.7:9090: connect: connection refused"
  ```
> [!IMPORTANT]
> **Nhận định:** 
> Việc kết nối bị `connection refused` đồng nghĩa với việc cổng `9090` (Prometheus) và `3100` (Loki) trên Master Node đang không phản hồi. Điều này xảy ra do dịch vụ ở Master bị tắt hoặc có tường lửa (firewall) chặn cổng truyền dữ liệu từ ngoài vào.

### 🟡 Sự cố 2: cAdvisor lỗi đọc phân vùng Docker (Read-Write Layer)
Trong log của container `cadvisor` xuất hiện liên tục các lỗi đọc phân vùng hệ thống của Docker:
```log
manager.go:1116] Failed to create existing container: /system.slice/docker-bf1c4451...scope: failed to identify the read-write layer ID ... no such file or directory
```
> [!WARNING]
> **Nhận định:**
> cAdvisor không thể xác định lớp đọc-ghi của các container đang chạy trên host. Lỗi này dẫn đến việc **không thể xuất được dữ liệu metrics chi tiết cấp container** (chỉ lấy được thông số tổng của máy Host).

---

## 🛠️ 3. Đề xuất Khắc phục (Recommendations)

1. **Khắc phục lỗi kết nối đến Master (`10.10.10.7`):**
   * Đảm bảo Prometheus và Loki trên máy Master đang chạy và lắng nghe trên các cổng `9090` và `3100`.
   * Cấu hình Firewall ở máy Master cho phép IP `10.10.10.10` gửi gói tin đến cổng `9090` (TCP) và `3100` (TCP).
   * Kiểm tra định tuyến (route) giữa hai máy `10.10.10.10` và `10.10.10.7` bằng lệnh `ping` hoặc `telnet 10.10.10.7 9090` từ máy `timescaledb-01`.

2. **Khắc phục lỗi cAdvisor:**
   * Cập nhật phiên bản cAdvisor trong tệp `agent/docker-compose.yml` lên bản mới hơn tương thích với phiên bản Docker hiện tại trên host (ví dụ: `gcr.io/cadvisor/cadvisor:v0.49.1`).
   * Đảm bảo phân quyền và mount thư mục đúng cho cAdvisor truy cập `/var/lib/docker` của máy Host.
