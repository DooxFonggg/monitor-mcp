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

The MCP Server (`mcp-bridge`) runs in **SSE Mode (Server-Sent Events)** on port `8000` of the Master server (`10.10.10.7`). Here is how you can connect your LLM clients to it:

### 1. Claude CLI / Claude Desktop (`claudecli`)
Claude Desktop runs locally and natively supports standard I/O (`stdio`). You can use the `mcp-remote` package via `npx` as a bridge proxy to connect to the remote SSE server:

1. Ensure Node.js and `npm` are installed on your client machine.
2. Open your Claude Desktop configuration file:
   * **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   * **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
3. Add the following entry to the `mcpServers` block:
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
4. Completely restart the Claude Desktop application.

---

### 2. VSCode / Cursor (`vscode`)

#### A. Cline / Roo Code Extension in VSCode
1. Open the **Cline** sidebar panel.
2. Click the **MCP Servers** (plug/stacked server) icon at the top right of the panel.
3. Select **Edit Global MCP** (or **Edit Project MCP**).
4. Add the SSE server directly:
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

#### B. Cursor IDE
1. Open **Cursor Settings** -> go to **Features** -> scroll down to the **MCP** section.
2. Click **+ Add New MCP Server**.
3. Fill in the following details:
   * **Name**: `monitoring-mcp`
   * **Type**: `SSE`
   * **URL**: `http://10.10.10.7:8000/sse`
4. Click **Save**.

---

### 3. Antigravity IDE / Agent (`antigravity`)
Antigravity IDE supports connecting directly to remote SSE MCP servers using the `mcp_config.json` configuration file.

1. Open the **Agent Panel** inside Antigravity IDE.
2. Click the **"..."** dropdown -> select **"Manage MCP Servers"** -> click **"View raw config"** (or open the file `%USERPROFILE%\.gemini\antigravity-ide\mcp_config.json` directly).
3. Add the server entry:
   ```json
   {
     "mcpServers": {
       "monitoring-mcp": {
         "url": "http://10.10.10.7:8000/sse"
       }
     }
   }
   ```
4. Save the file. The Agent will automatically detect the server and import the tools (`query_metrics`, `query_logs`, `get_system_status`, `explain_root_cause`).
