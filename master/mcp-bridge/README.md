# 🌉 MCP Monitoring Bridge

This folder contains a Model Context Protocol (MCP) server that exposes Prometheus metrics and Loki logs directly to your LLM clients (like Cursor IDE, VS Code MCP extensions, or Claude CLI).

---

## 🛠️ Exposing Tools to LLM

The MCP server exposes the following capabilities:
1. `query_metrics(query, start, end, step)`: Run PromQL queries to fetch real-time or historical host/container metrics (CPU, RAM, disk, etc.).
2. `query_logs(query, limit, start, end)`: Run LogQL queries to fetch Loki log lines from any container or system file.
3. `get_system_status()`: Retrieve a consolidated resource usage matrix (CPU, RAM, and Disk) for all monitored nodes.
4. `explain_root_cause(service_name)`: Fetch CPU, RAM, and recent error logs for a specific service and automatically diagnostic issues.

---

## 🚀 Connection Modes

### 1. Stdio Mode (Recommended for Cursor / VS Code / Claude CLI)

Stdio mode runs the Python script directly on your host machine. Your LLM client will spawn it as a background process.

#### Prerequisites
Install the Python dependencies on your host machine:
```bash
pip install mcp httpx uvicorn fastapi
```

#### Configuration for Cursor IDE & Claude Desktop
Add the following to your MCP settings file (e.g. `%APPDATA%/Claude/claude_desktop_config.json` or Cursor's MCP Settings):

```json
{
  "mcpServers": {
    "monitoring-mcp": {
      "command": "python",
      "args": [
        "d:/devops/monitoring/grafana-prometeus-loki-alloy/master/mcp-bridge/mcp_server.py"
      ],
      "env": {
        "PROMETHEUS_URL": "http://localhost:9090",
        "LOKI_URL": "http://localhost:3100",
        "MCP_MODE": "stdio"
      }
    }
  }
}
```

---

### 2. SSE Mode (For Web clients / OpenWebUI)

When you run `docker-compose up -d` in the `master` folder, the MCP bridge runs inside Docker in **SSE (Server-Sent Events) mode** and binds to port `8000`.

You can access the MCP server at:
- SSE endpoint: `http://localhost:8000/sse`
- Tools endpoint: `http://localhost:8000/tools`

You can connect web UI clients (like OpenWebUI) directly to `http://localhost:8000/sse`.
