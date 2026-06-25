# 📋 Kế Hoạch & Kịch Bản Kiểm Thử Cảnh Báo (TestCase alert.rules)

Tài liệu này hướng dẫn cách giả lập sự cố (stress test, dừng dịch vụ) để kiểm thử tất cả các luật cảnh báo trong tệp `alert.rules` đã cấu hình. Nó giúp đảm bảo toàn bộ dòng chảy dữ liệu từ **Alloy/cAdvisor ➔ Prometheus ➔ Alertmanager ➔ Telegram** hoạt động chính xác.

---

## 🛠️ Chuẩn Bị Trước Khi Kiểm Thử (Pre-requisites)

1. Đảm bảo cấu hình Telegram đã hợp lệ trong tệp `master/alertmanager/config.yml`:
   ```yaml
   receivers:
   - name: default-telegram
     telegram_configs:
     - api_url: https://api.telegram.org
       bot_token: "<YOUR_BOT_TOKEN>"  # Token thực tế từ @BotFather
       chat_id: <YOUR_CHAT_ID>        # Chat ID thực tế nhận tin
   ```
2. Đã tải lại cấu hình Prometheus sau khi sửa `alert.rules`:
   ```bash
   curl -X POST http://localhost:9090/-/reload
   ```
3. Đã tải lại cấu hình Alertmanager nếu có thay đổi token Telegram:
   ```bash
   curl -X POST http://localhost:9093/-/reload
   ```

---

## 📊 Bảng Tổng Hợp Kịch Bản Kiểm Thử (Test Case Summary)

| ID | Tên Cảnh Báo (Alert Name) | Mức Độ | Phương Pháp Giả Lập | Thời Gian Chờ | Trạng Thái Phục Hồi |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-01** | `ServiceDown` | Critical | Dừng container cAdvisor | 1 phút | Khởi động lại cAdvisor |
| **TC-02** | `SpecificContainerDown` | Critical | Dừng container `fake-logs` | 30 giây | Khởi động lại container |
| **TC-03** | `ContainerRestartLoop` | Warning | Chạy container crash liên tục | 1 phút | Xóa container test |
| **TC-04** | `HostCpuUsageCritical` / `Warning` | Critical/Warning | Chạy stress-ng giả lập tải CPU máy Host | 2-5 phút | Hết thời gian timeout |
| **TC-05** | `HostMemoryCritical` / `Warning` | Critical/Warning | Giả lập tiêu hao RAM máy Host | 2-3 phút | Hết thời gian timeout |
| **TC-06** | `HostDiskSpaceWarning` | Warning | Tạo tệp tin rác dung lượng lớn | 5 phút | Xóa tệp tin rác |
| **TC-07** | `ContainerMemoryUsageCritical` | Critical | Tiêu hao RAM container sát giới hạn limit | 1 phút | Dừng container test |

---

## 📝 Chi Tiết Từng Kịch Bản Kiểm Thử (Detailed Test Cases)

### 🔴 TC-01: Kiểm thử dịch vụ giám sát bị dừng (`ServiceDown`)
*   **Mục tiêu**: Đảm bảo nhận được cảnh báo ngay khi một dịch vụ quan trọng (ví dụ: `cAdvisor`) bị sập.
*   **Các bước thực hiện**:
    1. Trên máy Agent hoặc Master, gõ lệnh dừng cAdvisor:
       ```bash
       docker-compose stop cadvisor
       ```
    2. Truy cập Prometheus UI `http://localhost:9090/alerts`, tìm alert `ServiceDown`.
    3. **Trạng thái mong đợi**:
       - Sau **0 - 30 giây**: Chuyển sang màu vàng (**Pending**).
       - Sau **1 phút**: Chuyển sang màu đỏ (**Firing**).
       - **Telegram**: Nhận được tin nhắn định dạng: `[CRITICAL] Dịch vụ quan trọng bị dừng...` kèm IP của instance.
*   **Phục hồi**: Khởi động lại dịch vụ và kiểm tra tin nhắn `[RESOLVED]` trên Telegram:
    ```bash
    docker-compose start cadvisor
    ```

---

### 🔴 TC-02: Kiểm thử container ứng dụng bị sập (`SpecificContainerDown`)
*   **Mục tiêu**: Đảm bảo phát hiện container nghiệp vụ chính (như `fake-logs`) bị dừng.
*   **Các bước thực hiện**:
    1. Gõ lệnh dừng container `fake-logs`:
       ```bash
       docker-compose stop fake-logs
       ```
    2. Truy cập Prometheus UI, tìm alert `SpecificContainerDown`.
    3. **Trạng thái mong đợi**:
       - Sau **30 giây**: Alert chuyển sang **Firing**.
       - **Telegram**: Nhận tin nhắn: `[CRITICAL] Container fake-logs bị sập...`
*   **Phục hồi**: Khởi động lại container:
       ```bash
       docker-compose start fake-logs
       ```

---

### 🟡 TC-03: Kiểm thử vòng lặp khởi động lại của Container (`ContainerRestartLoop`)
*   **Mục tiêu**: Phát hiện các container bị lỗi cấu hình hoặc code dẫn đến crash liên tục (`CrashLoopBackOff`).
*   **Các bước thực hiện**:
    1. Chạy một container giả lập tự động thoát (exit 1) và tự động restart liên tục:
       ```bash
       docker run --name temp-restart-loop -d --restart=always alpine sh -c "sleep 5 && exit 1"
       ```
    2. **Trạng thái mong đợi**:
       - Sau **1 - 2 phút**: Container khởi động lại nhiều hơn 2 lần. Alert `ContainerRestartLoop` chuyển sang **Firing**.
       - **Telegram**: Nhận tin nhắn cảnh báo tên container `temp-restart-loop` liên tục restart.
*   **Phục hồi**: Dừng và xóa container thử nghiệm này:
       ```bash
       docker rm -f temp-restart-loop
       ```

---

### 🔴 / 🟡 TC-04: Kiểm thử quá tải CPU máy Host (`HostCpuUsageCritical` / `Warning`)
*   **Mục tiêu**: Giả lập CPU máy chủ tăng cao để kiểm thử cảnh báo tài nguyên hệ thống.
*   **Các bước thực hiện**:
    1. Cài đặt và chạy công cụ `stress-ng` trực tiếp trên máy Host (hoặc thông qua container Docker có quyền hạn cao) để ép CPU chạy 100% trong 5 phút (300 giây):
       ```bash
       docker run --rm -it --privileged --pid=host ltargett/stress-ng --cpu 4 --timeout 300s
       ```
       *(Thay số `4` bằng số core CPU thực tế của máy của bạn)*
    2. **Trạng thái mong đợi**:
       - Sau **2 phút**: Đạt ngưỡng > 95% CPU, alert `HostCpuUsageCritical` chuyển sang **Firing**.
       - **Telegram**: Nhận tin nhắn cảnh báo CPU quá tải nghiêm trọng.
*   **Phục hồi**: Lệnh stress sẽ tự động kết thúc sau 300 giây (5 phút), hệ thống sẽ nguội đi và gửi tin nhắn `RESOLVED`. (Hoặc nhấn `Ctrl + C` để dừng lệnh stress sớm).

---

### 🔴 / 🟡 TC-05: Kiểm thử RAM máy Host sắp đầy (`HostMemoryCritical` / `Warning`)
*   **Mục tiêu**: Ép RAM hệ thống tăng cao để kích hoạt cảnh báo RAM.
*   **Các bước thực hiện**:
    1. Chạy stress-ng để chiếm dụng bộ nhớ RAM (Ví dụ máy của bạn có 2GB RAM, ta sẽ ép chiếm dụng 1.8GB RAM trong 5 phút):
       ```bash
       docker run --rm -it --privileged --pid=host ltargett/stress-ng --vm 1 --vm-bytes 1800M --timeout 300s
       ```
       *(Hãy điều chỉnh thông số `--vm-bytes` phù hợp với dung lượng RAM máy chủ của bạn để tránh sập máy).*
    2. **Trạng thái mong đợi**:
       - Sau **2 phút**: Sử dụng RAM > 95%, kích hoạt cảnh báo `HostMemoryCritical` gửi về Telegram.
*   **Phục hồi**: Tiến trình stress tự giải phóng RAM sau 5 phút hoặc nhấn `Ctrl + C` để giải phóng lập tức.

---

### 🟡 TC-06: Kiểm thử dung lượng ổ đĩa trống sắp hết (`HostDiskSpaceWarning`)
*   **Mục tiêu**: Kiểm thử cảnh báo khi phân vùng ghi đĩa (`/`) sắp đầy.
*   **Các bước thực hiện**:
    1. Xem dung lượng ổ cứng hiện tại bằng lệnh `df -h /`.
    2. Tạo một tệp tin rác lớn chiếm dung lượng để đẩy mức sử dụng phân vùng root lên trên **85%**:
       ```bash
       # Ví dụ tạo file rác dung lượng 10 GB
       fallocate -l 10G /tmp/dummy_large_file
       ```
       *(Hoặc dùng lệnh dd nếu hệ điều hành không hỗ trợ fallocate)*:
       ```bash
       dd if=/dev/zero of=/tmp/dummy_large_file bs=1M count=10000
       ```
    3. **Trạng thái mong đợi**:
       - Sau **5 phút**: Mức sử dụng phân vùng `/` vượt 85%. Alert `HostDiskSpaceWarning` kích hoạt.
       - **Telegram**: Nhận cảnh báo dung lượng đĩa sắp đầy.
*   **Phục hồi**: Xóa tệp tin rác đã tạo để trả lại dung lượng:
       ```bash
       rm -f /tmp/dummy_large_file
       ```

---

### 🔴 TC-07: Kiểm thử cảnh báo giới hạn RAM của Container (`ContainerMemoryUsageCritical`)
*   **Mục tiêu**: Đảm bảo phát hiện container vượt ngưỡng cấp phát RAM và sắp bị hệ điều hành tắt (Out of Memory - OOM).
*   **Các bước thực hiện**:
    1. Khởi chạy một container thử nghiệm bị giới hạn RAM tối đa là `200 Megabytes`:
       ```bash
       docker run --name temp-oom-test -m 200M -d alpine sh -c "apk add --no-cache stress-ng && stress-ng --vm 1 --vm-bytes 190M --timeout 180s"
       ```
       *(Lệnh này chạy stress chiếm dụng 190MB RAM trong tổng số 200MB được cấp ~ 95% RAM giới hạn)*
    2. **Trạng thái mong đợi**:
       - Sau **1 phút**: Sử dụng RAM đạt 95% dung lượng tối đa. Alert `ContainerMemoryUsageCritical` chuyển sang **Firing**.
       - **Telegram**: Nhận tin nhắn cảnh báo đỏ `Nguy cơ OOM: Container cạn kiệt RAM (Container: temp-oom-test)`.
*   **Phục hồi**: Container sẽ tự kết thúc sau 3 phút hoặc xóa nó sớm bằng lệnh:
       ```bash
       docker rm -f temp-oom-test
       ```
