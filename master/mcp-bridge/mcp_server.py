import os
import sys
import re
import time
import httpx
import logging
from typing import Optional
from mcp import FastMCP

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("monitoring-mcp")

def load_dotenv():
    # Check current directory and script directory for .env
    paths = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    ]
    for path in paths:
        if os.path.exists(path):
            logger.info(f"Loading environment variables from: {path}")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
                break
            except Exception as e:
                logger.error(f"Error reading .env file: {e}")

# Load environment variables from .env if present
load_dotenv()

# Environment configurations
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
LOKI_URL = os.environ.get("LOKI_URL", "http://localhost:3100").rstrip("/")

# Initialize MCP Server
mcp = FastMCP("Monitoring Bridge")

def parse_relative_time(t_str: Optional[str]) -> float:
    """Helper to convert relative duration string (e.g., '15m', '2h') to absolute epoch timestamp."""
    now = time.time()
    if not t_str:
        return now
    
    # Check if already a float or numeric timestamp
    try:
        return float(t_str)
    except ValueError:
        pass
    
    match = re.match(r"^(\d+)([shmd])$", t_str.strip().lower())
    if not match:
        return now
    
    value, unit = match.groups()
    value = int(value)
    
    deltas = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400
    }
    
    return now - (value * deltas.get(unit, 0))

@mcp.tool()
async def query_metrics(query: str, start: Optional[str] = None, end: Optional[str] = None, step: str = "15s") -> str:
    """
    Query metrics from Prometheus.
    If 'start' is provided, it does a range query. Otherwise, it does an instant query.
    Arguments:
      - query: PromQL query string (e.g., 'node_cpu_seconds_total').
      - start: Start time for range query (e.g., '1h', '15m', or unix timestamp).
      - end: End time for range query (e.g., 'now', '10m', or unix timestamp).
      - step: Query resolution step width (e.g., '15s', '1m').
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if start:
                # Range Query
                start_ts = parse_relative_time(start)
                end_ts = parse_relative_time(end) if end else time.time()
                
                url = f"{PROMETHEUS_URL}/api/v1/query_range"
                params = {
                    "query": query,
                    "start": str(start_ts),
                    "end": str(end_ts),
                    "step": step
                }
                logger.info(f"Prometheus Range Query: {url} params={params}")
                response = await client.get(url, params=params)
            else:
                # Instant Query
                url = f"{PROMETHEUS_URL}/api/v1/query"
                params = {"query": query}
                logger.info(f"Prometheus Instant Query: {url} params={params}")
                response = await client.get(url, params=params)

            if response.status_code != 200:
                return f"Prometheus returned error status {response.status_code}: {response.text}"
            
            data = response.json()
            if data.get("status") != "success":
                return f"Prometheus query failed: {data.get('error', 'Unknown error')}"
            
            results = data.get("data", {}).get("result", [])
            if not results:
                return "No metric series matched the query."
            
            lines = []
            for item in results:
                metric = item.get("metric", {})
                metric_str = ", ".join(f'{k}="{v}"' for k, v in metric.items())
                
                if "value" in item:
                    # Instant value
                    t, val = item["value"]
                    lines.append(f"Metric: {{{metric_str}}} | Value: {val} (at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(t)))})")
                elif "values" in item:
                    # Range values
                    vals = item["values"]
                    lines.append(f"Metric: {{{metric_str}}}")
                    # Summarize values if there are too many
                    if len(vals) > 10:
                        lines.append(f"  [Showing 10 of {len(vals)} data points]")
                        step_size = len(vals) // 10
                        sampled = [vals[i] for i in range(0, len(vals), step_size)][:10]
                    else:
                        sampled = vals
                        
                    for t, val in sampled:
                        time_formatted = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(t)))
                        lines.append(f"  - {time_formatted}: {val}")
                        
            return "\n".join(lines)
            
        except httpx.RequestError as exc:
            return f"Failed to connect to Prometheus at {PROMETHEUS_URL}: {exc}"

@mcp.tool()
async def query_logs(query: str, limit: int = 50, start: str = "1h", end: Optional[str] = None) -> str:
    """
    Query logs from Loki using LogQL.
    Arguments:
      - query: LogQL query string (e.g., '{container="fake-logs"}' or '{job="varlogs"} |= "error"').
      - limit: Maximum number of log entries to retrieve. Default is 50.
      - start: Start time (e.g., '1h', '30m' or unix timestamp). Default is '1h'.
      - end: End time (e.g., '10m' or unix timestamp).
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            start_ts = parse_relative_time(start)
            end_ts = parse_relative_time(end) if end else time.time()
            
            url = f"{LOKI_URL}/loki/api/v1/query_range"
            # Loki expects nanoseconds as a string representation
            params = {
                "query": query,
                "limit": str(limit),
                "start": str(int(start_ts * 1e9)),
                "end": str(int(end_ts * 1e9)),
                "direction": "BACKWARD"
            }
            logger.info(f"Loki Query: {url} params={params}")
            response = await client.get(url, params=params)
            
            if response.status_code != 200:
                return f"Loki returned error status {response.status_code}: {response.text}"
                
            data = response.json()
            if data.get("status") != "success":
                return f"Loki query failed: {data.get('error', 'Unknown error')}"
                
            results = data.get("data", {}).get("result", [])
            if not results:
                return "No logs matched the query."
                
            entries = []
            for stream_item in results:
                labels = stream_item.get("stream", {})
                labels_str = ", ".join(f'{k}="{v}"' for k, v in labels.items())
                
                for timestamp_ns, line in stream_item.get("values", []):
                    ts_seconds = float(timestamp_ns) / 1e9
                    time_formatted = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts_seconds))
                    entries.append((ts_seconds, f"[{time_formatted}] {{{labels_str}}} {line.strip()}"))
            
            # Sort all log lines chronologically
            entries.sort(key=lambda x: x[0])
            return "\n".join(e[1] for e in entries)
            
        except httpx.RequestError as exc:
            return f"Failed to connect to Loki at {LOKI_URL}: {exc}"

@mcp.tool()
async def get_system_status() -> str:
    """
    Get current CPU, Memory, and Disk usage summary across all monitored servers.
    Queries Prometheus to calculate actual usages.
    """
    cpu_query = "100 - (avg by (instance) (irate(node_cpu_seconds_total{mode='idle'}[5m])) * 100)"
    mem_query = "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100"
    disk_query = "(node_filesystem_size_bytes{mountpoint='/'} - node_filesystem_free_bytes{mountpoint='/'}) / node_filesystem_size_bytes{mountpoint='/'} * 100"
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            # Query CPU
            cpu_res = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": cpu_query})
            # Query Mem
            mem_res = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": mem_query})
            # Query Disk
            disk_res = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": disk_query})
            
            if cpu_res.status_code != 200 or mem_res.status_code != 200 or disk_res.status_code != 200:
                return "Failed to query Prometheus for resources. Make sure Prometheus is running and populated."
                
            cpu_data = cpu_res.json().get("data", {}).get("result", [])
            mem_data = mem_res.json().get("data", {}).get("result", [])
            disk_data = disk_res.json().get("data", {}).get("result", [])
            
            # Map by instance
            status = {}
            for item in cpu_data:
                inst = item.get("metric", {}).get("instance", "unknown")
                status[inst] = {"cpu": round(float(item["value"][1]), 2)}
                
            for item in mem_data:
                inst = item.get("metric", {}).get("instance", "unknown")
                if inst not in status: status[inst] = {}
                status[inst]["mem"] = round(float(item["value"][1]), 2)
                
            for item in disk_data:
                inst = item.get("metric", {}).get("instance", "unknown")
                if inst not in status: status[inst] = {}
                status[inst]["disk"] = round(float(item["value"][1]), 2)
                
            if not status:
                return "No host metrics currently available. Verify that Grafana Alloy agents are pushing metrics to Prometheus."
                
            report = ["### 🖥️ Host Resource Usage Status\n"]
            report.append("| Instance (Host) | CPU Usage | RAM Usage | Root Disk Usage |")
            report.append("| :--- | :---: | :---: | :---: |")
            
            for inst, metrics in status.items():
                cpu = f"{metrics.get('cpu', 'N/A')}%"
                mem = f"{metrics.get('mem', 'N/A')}%"
                disk = f"{metrics.get('disk', 'N/A')}%"
                report.append(f"| {inst} | {cpu} | {mem} | {disk} |")
                
            return "\n".join(report)
            
        except Exception as exc:
            return f"Error retrieving system status: {exc}"

@mcp.tool()
async def explain_root_cause(service_name: str) -> str:
    """
    Perform automatic log and resource correlation for a service to identify issues.
    Arguments:
      - service_name: Name of the service/container to diagnose (e.g. 'fake-logs').
    """
    # 1. Fetch CPU and RAM metrics
    cpu_q = f"sum(rate(container_cpu_usage_seconds_total{{name=~'.*{service_name}.*',image!=''}}[5m])) * 100"
    mem_q = f"sum(container_memory_usage_bytes{{name=~'.*{service_name}.*',image!=''}})"
    
    # 2. Fetch error logs
    log_q = f"{{container=~'.*{service_name}.*'}} |= \"error\" or \"fail\" or \"exception\" or \"warn\""
    
    async with httpx.AsyncClient(timeout=12.0) as client:
        try:
            # Query Metrics
            cpu_res = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": cpu_q})
            mem_res = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": mem_q})
            
            cpu_val = "N/A"
            mem_val = "N/A"
            
            if cpu_res.status_code == 200:
                res = cpu_res.json().get("data", {}).get("result", [])
                if res: cpu_val = f"{round(float(res[0]['value'][1]), 2)}% of host CPU core"
                
            if mem_res.status_code == 200:
                res = mem_res.json().get("data", {}).get("result", [])
                if res:
                    mem_bytes = float(res[0]['value'][1])
                    mem_val = f"{round(mem_bytes / (1024*1024), 2)} MB"
            
            # Query Logs
            start_ts = time.time() - 900 # last 15 mins
            params = {
                "query": log_q,
                "limit": "15",
                "start": str(int(start_ts * 1e9)),
                "direction": "BACKWARD"
            }
            log_res = await client.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params)
            
            logs = "No matching error or warning logs found in the last 15 minutes."
            if log_res.status_code == 200:
                res = log_res.json().get("data", {}).get("result", [])
                if res:
                    lines = []
                    for item in res:
                        for timestamp_ns, line in item.get("values", []):
                            ts = float(timestamp_ns) / 1e9
                            time_formatted = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
                            lines.append(f"[{time_formatted}] {line.strip()}")
                    lines.sort()
                    logs = "\n".join(lines)
            
            report = [
                f"## 🔍 Root Cause Analysis Report for Service: `{service_name}`\n",
                f"### 📊 Current Resource Usage:",
                f"- **CPU Usage**: {cpu_val}",
                f"- **Memory Usage**: {mem_val}\n",
                f"### 📋 Recent Error/Warning Logs (Last 15m):",
                "```log",
                logs,
                "```"
            ]
            return "\n".join(report)
            
        except Exception as exc:
            return f"Error executing RCA for service `{service_name}`: {exc}"

if __name__ == "__main__":
    import uvicorn
    # If MCP_MODE is sse, start fastapi server. Otherwise run as stdio
    mode = os.environ.get("MCP_MODE", "stdio").strip().lower()
    
    if mode == "sse" or "--sse" in sys.argv:
        logger.info("Starting MCP Server in SSE (HTTP) mode on port 8000")
        mcp.run("sse")
    else:
        logger.info("Starting MCP Server in Stdio mode")
        mcp.run("stdio")
