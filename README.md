# 📘 Hướng Dẫn Kiến Trúc & Vận Hành Hệ Thống Giám Sát (Grafana Alloy & MCP Server)

Hệ thống giám sát này sử dụng kiến trúc phân tán hiện đại dựa trên **Grafana Alloy** đóng vai trò là Agent thu thập dữ liệu tập trung (Logs, Metrics) và đẩy về **Master Node**. Ngoài ra, hệ thống tích hợp **MCP Server (Model Context Protocol)** để các mô hình ngôn ngữ lớn (LLM) như Cursor IDE, Claude CLI có thể truy vấn trực tiếp và phân tích tài nguyên (RAM, CPU, Disk, Logs).

---

## 🏛️ Sơ Đồ Kiến Trúc & Dòng Chảy Dữ Liệu (Data Flow)

```mermaid
graph TD
    %% Nodes
    subgraph "DEV EXPERIENCE"
        A[Cursor IDE / Claude CLI]
    end

    subgraph "AI OBSERVABILITY LAYER"
        B[MCP Server / mcp-bridge]
    end

    subgraph "CENTRAL OBSERVABILITY STACK (MASTER)"
        C[(Prometheus TSDB)]
        D[(Loki Logs Store)]
        E[Grafana Dashboards]
        F[Alertmanager]
    end

    subgraph "EDGE LAYER (AGENT NODES & MASTER LOCAL)"
        G[Grafana Alloy Agent]
        H[cAdvisor Container]
        I[Host System /var/log & CPU/RAM]
    end

    %% Flows
    A <-->|Stdio / SSE JSON-RPC| B
    B -->|PromQL| C
    B -->|LogQL| D
    E -->|Read Metrics| C
    E -->|Read Logs| D
    C -->|Alert Rules| F

    I -->|Host Logs & Stats| G
    H -->|Container Metrics| G
    G -->|Remote Write Metrics| C
    G -->|Push Logs| D
```

### 1. Luồng dữ liệu Metrics:
* **Thu thập (Collect)**: Grafana Alloy sử dụng module tích hợp sẵn `prometheus.exporter.unix` để lấy metric của Host (CPU, RAM, Disk) và scrape endpoint của `cAdvisor` để lấy thông số của các Docker container.
* **Vận chuyển (Transport)**: Alloy nén và đẩy dữ liệu qua giao thức Prometheus `remote_write` tới cổng `9090` của Master Node.
* **Lưu trữ & Hiển thị**: Prometheus lưu trữ dữ liệu Time-series. Grafana đọc dữ liệu hiển thị lên các biểu đồ thời gian thực.

### 2. Luồng dữ liệu Logs:
* **Thu thập (Collect)**: Alloy đọc trực tiếp từ Docker Socket (`/var/run/docker.sock`) đối với container logs và từ đường dẫn `/var/log/*` đối với syslog của Host.
* **Vận chuyển (Transport)**: Alloy định dạng nhãn (labels) như `container` hoặc `job` rồi đẩy qua API HTTP của Loki (`/loki/api/v1/push`) tại cổng `3100` của Master.

---

## 📂 Cơ Cấu Thư Mục Dự Án

```
grafana-prometeus-loki-alloy/
├── master/                         # Cấu hình tại máy chủ Master (View tập trung)
│   ├── docker-compose.yml          # Chạy Prometheus, Loki, Grafana, Alertmanager, Alloy, cAdvisor, mcp-bridge
│   ├── config.alloy                # Thu thập log/metric nội bộ của chính máy Master
│   ├── prometheus/
│   │   ├── prometheus.yml          # Cấu hình Scrape & kích hoạt Receiver
│   │   └── alert.rules             # Luật cảnh báo (CPU, RAM, Disk, Container Down)
│   ├── loki/
│   │   └── loki-config.yaml        # Cấu hình lưu trữ tệp tin log
│   ├── grafana/
│   │   └── provisioning/           # Tự động nạp Datasource và Dashboard JSON
│   ├── alertmanager/
│   │   └── config.yml              # Cấu hình định tuyến cảnh báo (Slack, Telegram)
│   └── mcp-bridge/                 # MCP Server trung gian kết nối AI với Prometheus/Loki
│
└── agent/                          # Cấu hình cài đặt tại các máy Agent (Client Nodes)
    ├── docker-compose.yml          # Khởi động cAdvisor & Grafana Alloy Agent
    └── config.alloy                # Chỉ định thu thập và đẩy dữ liệu về IP của Master
```

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy Hệ Thống

### Bước 1: Khởi động Master Node (Trung tâm)
Tại máy chủ Master, di chuyển vào thư mục `master` và chạy lệnh docker-compose:
```bash
cd master
docker-compose up -d --build
```
Lệnh này sẽ khởi tạo toàn bộ hạ tầng lưu trữ và hiển thị:
* **Grafana**: `http://localhost:3000` (Tài khoản: `admin` / Mật khẩu mặc định: `changeme`). Các dashboard giám sát Host và Container đã được tích hợp sẵn.
* **Prometheus**: `http://localhost:9090`
* **Loki**: `http://localhost:3100`
* **MCP Bridge (SSE Mode)**: `http://localhost:8000/sse`

---

### Bước 2: Khởi động Agent Node (Máy Client cần giám sát)
Để giám sát một máy chủ khác (Agent), bạn copy thư mục `agent` sang máy đó và thực hiện cấu hình thông qua file `.env`. Việc này giúp bạn dùng chung cấu hình `docker-compose.yml` và `config.alloy` cho mọi Agent mà không cần sửa code bên trong.

1. Tạo file `.env` từ file ví dụ:
   ```bash
   cp .env.example .env
   ```
   *(Trên Windows PowerShell: `copy .env.example .env`)*

2. Mở file `agent/.env` và cập nhật các thông tin sau:
   - **PROMETHEUS_URL**: Thay thế `<master-ip>` bằng IP thực tế của máy chủ Master.
   - **LOKI_URL**: Thay thế `<master-ip>` bằng IP thực tế của máy chủ Master.
   - **AGENT_NAME**: Đặt tên gợi nhớ cho Agent này (ví dụ: `timescaledb-01`, `edge-01`, ...).

   ```env
   PROMETHEUS_URL=http://<YOUR_MASTER_IP>:9090/api/v1/write
   LOKI_URL=http://<YOUR_MASTER_IP>:3100/loki/api/v1/push
   AGENT_NAME=edge-01
   ```

3. Khởi động Agent bằng lệnh:
   ```bash
   cd agent
   docker-compose up -d
   ```

> [!TIP]
> **Nhãn `instance` tự động:**
> Grafana Alloy sẽ tự động sử dụng biến `AGENT_NAME` từ file `.env` làm giá trị nhãn `instance` cho tất cả Metrics và Logs thu thập được từ máy này. Nhờ đó, trên giao diện Grafana hoặc khi truy vấn qua MCP Server, bạn sẽ thấy tên thiết bị thân thiện thay vì địa chỉ IP và Port khó nhớ.

*(Lưu ý: Grafana Alloy trên máy Master cũng tự động thu thập thông số của chính máy Master và được gán nhãn `instance=master-node` mặc định).*

---

## 🤖 Kết Nối MCP Server Vào AI Clients (Claude CLI, VSCode/Cursor, Antigravity)

MCP Server (`mcp-bridge`) chạy dưới dạng **SSE Mode (Server-Sent Events)** tại cổng `8000` của server Master (`10.10.10.7`). Dưới đây là cách cấu hình chi tiết cho 3 loại AI Client phổ biến để truy vấn trực tiếp dữ liệu logs & metrics:

### 1. Claude CLI / Claude Desktop (`claudecli`)
Vì Claude Desktop chạy local và chủ yếu hỗ trợ giao thức `stdio` mặc định, chúng ta sử dụng gói `mcp-remote` (thông qua `npx`) làm proxy bridge để kết nối tới server SSE từ xa.

1. Đảm bảo máy chạy Claude Desktop đã cài đặt Node.js/npm.
2. Mở file cấu hình `claude_desktop_config.json`:
   * **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   * **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
3. Thêm cấu hình mcp server như sau:
   ```json
   {
     "mcpServers": {
       "monitoring-mcp": {
         "command": "npx",
         "args": [
           "-y",
           "mcp-remote",
           "http://10.10.10.7:8000/sse"
         ]
       }
     }
   }
   ```
4. Khởi động lại (completely restart) ứng dụng Claude Desktop.

---

### 2. VSCode / Cursor IDE (`vscode`)

#### A. Đối với extension Cline / Roo Code trên VSCode
1. Mở panel **Cline** trên sidebar.
2. Nhấn vào biểu tượng **MCP Servers** (hình ổ cắm điện/ổ cứng xếp chồng) ở góc trên.
3. Chọn **Edit Global MCP** (hoặc **Edit Project MCP**).
4. Thêm cấu hình server SSE trực tiếp:
   ```json
   {
     "mcpServers": {
       "monitoring-mcp": {
         "type": "sse",
         "url": "http://10.10.10.7:8000/sse",
         "disabled": false
       }
     }
   }
   ```

#### B. Đối với Cursor IDE
1. Mở **Settings** -> chọn tab **Features** -> cuộn xuống phần **MCP**.
2. Nhấn nút **+ Add New MCP Server**.
3. Điền thông tin cấu hình:
   * **Name**: `monitoring-mcp`
   * **Type**: `SSE`
   * **URL**: `http://10.10.10.7:8000/sse`
4. Chọn **Save**.

---

### 3. Antigravity IDE / Agent (`antigravity`)
Antigravity IDE hỗ trợ kết nối trực tiếp đến các MCP server qua giao thức Streamable HTTP thông qua file cấu hình `mcp_config.json`.

1. Truy cập panel điều khiển **Agent Panel** trong Antigravity IDE.
2. Click vào biểu tượng ba chấm **"..."** -> chọn **"Manage MCP Servers"** -> chọn **"View raw config"** (hoặc mở trực tiếp file `%USERPROFILE%\.gemini\antigravity-ide\mcp_config.json`).
3. Cập nhật cấu hình:
   ```json
   {
     "mcpServers": {
       "monitoring-mcp": {
         "serverURL": "http://10.10.10.7:8000/mcp"
       }
     }
   }
   ```
4. Lưu tệp và Agent sẽ tự động nạp các công cụ (`query_metrics`, `query_logs`, `get_system_status`, `explain_root_cause`).

---

### 💡 Ví dụ câu lệnh prompt sử dụng AI kết hợp MCP:
* *"Hãy kiểm tra tài nguyên hệ thống hiện tại của toàn bộ các server"* (gọi tool `get_system_status`).
* *"Đọc log của container fake-logs trong 5 phút qua xem có lỗi gì không"* (gọi tool `query_logs`).
* *"Container fake-logs bị lỗi gì thế? Hãy kiểm tra tài nguyên của nó và giải thích nguyên nhân gốc"* (gọi tool `explain_root_cause`).
