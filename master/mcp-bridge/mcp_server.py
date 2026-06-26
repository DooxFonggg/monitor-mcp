import os
import sys
import re
import time
import httpx
import logging
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    try:
        from fastmcp import FastMCP
    except ImportError:
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

try:
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:
    try:
        from mcp.server.sse import TransportSecuritySettings
    except ImportError:
        TransportSecuritySettings = None

# Ensure FastMCP binds to 0.0.0.0 and port 8000 for SSE mode
os.environ["FASTMCP_HOST"] = os.environ.get("FASTMCP_HOST", "0.0.0.0")
os.environ["FASTMCP_PORT"] = os.environ.get("FASTMCP_PORT", "8000")
os.environ["FASTMCP_SERVER_HOST"] = os.environ.get("FASTMCP_SERVER_HOST", "0.0.0.0")
os.environ["FASTMCP_SERVER_PORT"] = os.environ.get("FASTMCP_SERVER_PORT", "8000")

# Initialize MCP Server
mcp_kwargs = {
    "host": os.environ.get("FASTMCP_HOST", "0.0.0.0"),
    "port": int(os.environ.get("FASTMCP_PORT", "8000"))
}
if TransportSecuritySettings is not None:
    mcp_kwargs["transport_security"] = TransportSecuritySettings(enable_dns_rebinding_protection=False)

mcp = FastMCP("Monitoring Bridge", **mcp_kwargs)

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
    disk_query = "(node_filesystem_size_bytes{fstype=~'ext[2-4]|xfs|btrfs'} - node_filesystem_free_bytes{fstype=~'ext[2-4]|xfs|btrfs'}) / node_filesystem_size_bytes{fstype=~'ext[2-4]|xfs|btrfs'} * 100"
    
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
                
            disk_usages = {}
            for item in disk_data:
                inst = item.get("metric", {}).get("instance", "unknown")
                mount = item.get("metric", {}).get("mountpoint", "unknown")
                if item.get("metric", {}).get("fstype") == "rootfs":
                    continue
                usage = round(float(item["value"][1]), 2)
                if inst not in disk_usages:
                    disk_usages[inst] = []
                disk_usages[inst].append(f"{mount}: {usage}%")
                
            if not status:
                return "No host metrics currently available. Verify that Grafana Alloy agents are pushing metrics to Prometheus."
                
            report = ["### 🖥️ Host Resource Usage Status\n"]
            report.append("| Instance (Host) | CPU Usage | RAM Usage | Disk Usage (Mountpoint: %) |")
            report.append("| :--- | :---: | :---: | :--- |")
            
            for inst, metrics in status.items():
                cpu = f"{metrics.get('cpu', 'N/A')}%"
                mem = f"{metrics.get('mem', 'N/A')}%"
                
                disks = disk_usages.get(inst, [])
                if disks:
                    disk_str = ", ".join(disks)
                else:
                    disk_str = "N/A"
                report.append(f"| {inst} | {cpu} | {mem} | {disk_str} |")
                
            return "\n".join(report)
            
        except Exception as exc:
            return f"Error retrieving system status: {exc}"

@mcp.tool()
async def get_host_details(instance: str) -> str:
    """
    Get detailed resource utilization metrics for a specific host, including CPU cores, load,
    RAM (total/used/free), Disk Space (size/used/free/mountpoints), Disk IOPS, and Network traffic.
    Arguments:
      - instance: The host name or instance identifier (e.g. 'timescaledb-ha-01').
    """
    queries = {
        "cpu_cores": f"count(count(node_cpu_seconds_total{{instance=~'.*{instance}.*'}} ) by (cpu))",
        "cpu_usage": f"100 - (avg(irate(node_cpu_seconds_total{{instance=~'.*{instance}.*', mode='idle'}}[5m])) * 100)",
        "load_1m": f"node_load1{{instance=~'.*{instance}.*'}}",
        "mem_total": f"node_memory_MemTotal_bytes{{instance=~'.*{instance}.*'}}",
        "mem_avail": f"node_memory_MemAvailable_bytes{{instance=~'.*{instance}.*'}}",
        "disk_size": f"node_filesystem_size_bytes{{instance=~'.*{instance}.*', fstype=~'ext[2-4]|xfs|btrfs'}}",
        "disk_free": f"node_filesystem_free_bytes{{instance=~'.*{instance}.*', fstype=~'ext[2-4]|xfs|btrfs'}}",
        "disk_read_bytes": f"rate(node_disk_read_bytes_total{{instance=~'.*{instance}.*'}}[5m])",
        "disk_write_bytes": f"rate(node_disk_written_bytes_total{{instance=~'.*{instance}.*'}}[5m])",
        "net_rx_bytes": f"sum(rate(node_network_receive_bytes_total{{instance=~'.*{instance}.*', device!='lo'}}[5m]))",
        "net_tx_bytes": f"sum(rate(node_network_transmit_bytes_total{{instance=~'.*{instance}.*', device!='lo'}}[5m]))"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        results = {}
        for name, query in queries.items():
            try:
                res = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query})
                if res.status_code == 200:
                    data = res.json().get("data", {}).get("result", [])
                    results[name] = data
                else:
                    results[name] = []
            except Exception as e:
                logger.error(f"Error querying {name}: {e}")
                results[name] = []
                
        def get_value(data_list, default="N/A"):
            if data_list and len(data_list) > 0:
                return data_list[0]["value"][1]
            return default
            
        cpu_cores = get_value(results["cpu_cores"])
        cpu_usage = get_value(results["cpu_usage"])
        load_1m = get_value(results["load_1m"])
        mem_total = get_value(results["mem_total"])
        mem_avail = get_value(results["mem_avail"])
        net_rx = get_value(results["net_rx_bytes"])
        net_tx = get_value(results["net_tx_bytes"])
        
        ram_report = "N/A"
        if mem_total != "N/A" and mem_avail != "N/A":
            total_gb = float(mem_total) / (1024**3)
            avail_gb = float(mem_avail) / (1024**3)
            used_gb = total_gb - avail_gb
            usage_pct = (used_gb / total_gb) * 100
            ram_report = f"{round(used_gb, 2)} GB / {round(total_gb, 2)} GB ({round(usage_pct, 2)}%)"
            
        disk_rows = []
        disk_size_data = results["disk_size"]
        disk_free_data = results["disk_free"]
        
        free_map = {}
        for item in disk_free_data:
            mount = item.get("metric", {}).get("mountpoint", "unknown")
            free_map[mount] = float(item["value"][1])
            
        for item in disk_size_data:
            metric = item.get("metric", {})
            mount = metric.get("mountpoint", "unknown")
            device = metric.get("device", "unknown")
            fstype = metric.get("fstype", "unknown")
            size = float(item["value"][1])
            free = free_map.get(mount, 0.0)
            used = size - free
            used_pct = (used / size) * 100 if size > 0 else 0
            
            size_gb = size / (1024**3)
            used_gb = used / (1024**3)
            free_gb = free / (1024**3)
            
            disk_rows.append(
                f"| `{device}` | `{mount}` | `{fstype}` | {round(size_gb, 2)} GB | {round(used_gb, 2)} GB | {round(free_gb, 2)} GB | {round(used_pct, 2)}% |"
            )
            
        disk_report = "\n".join(disk_rows) if disk_rows else "| N/A | N/A | N/A | N/A | N/A | N/A | N/A |"
        
        io_rows = []
        for item in results["disk_read_bytes"]:
            dev = item.get("metric", {}).get("device", "unknown")
            read_rate_kb = float(item["value"][1]) / 1024
            write_rate_kb = 0.0
            for w_item in results["disk_write_bytes"]:
                if w_item.get("metric", {}).get("device") == dev:
                    write_rate_kb = float(w_item["value"][1]) / 1024
                    break
            io_rows.append(f"| `{dev}` | {round(read_rate_kb, 2)} KB/s | {round(write_rate_kb, 2)} KB/s |")
            
        io_report = "\n".join(io_rows) if io_rows else "| N/A | N/A | N/A |"
        
        net_rx_kb = float(net_rx) / 1024 if net_rx != "N/A" else 0.0
        net_tx_kb = float(net_tx) / 1024 if net_tx != "N/A" else 0.0
        
        report = [
            f"## 📊 Detailed Host Report for Instance: `{instance}`\n",
            f"### ⚡ CPU & Load Info",
            f"- **CPU Cores**: {cpu_cores}",
            f"- **CPU Usage (5m avg)**: {round(float(cpu_usage), 2) if cpu_usage != 'N/A' else 'N/A'}%",
            f"- **Load Average (1m)**: {load_1m}\n",
            f"### 🧠 Memory (RAM) Info",
            f"- **RAM Usage**: {ram_report}\n",
            f"### 🌐 Network Traffic",
            f"- **Incoming (Rx Rate)**: {round(net_rx_kb, 2)} KB/s",
            f"- **Outgoing (Tx Rate)**: {round(net_tx_kb, 2)} KB/s\n",
            f"### 💾 Disk Space Usage",
            f"| Device | Mountpoint | FSType | Size | Used | Free | Usage (%) |",
            f"| :--- | :--- | :--- | :--- | :--- | :--- | :---: |",
            disk_report,
            f"\n### 🔄 Disk I/O Rates (5m average)",
            f"| Device | Read Throughput | Write Throughput |",
            f"| :--- | :--- | :--- |",
            io_report
        ]
        return "\n".join(report)

@mcp.tool()
async def analyze_resource_consumers(instance: str) -> str:
    """
    Identify which docker containers or systemd units are the top resource consumers
    (CPU, RAM, Disk writes) on a host, and summarize their log volume in Loki.
    Arguments:
      - instance: The host name or instance identifier (e.g. 'timescaledb-ha-01').
    """
    container_mem_q = f"topk(5, sum by (name) (container_memory_working_set_bytes{{instance=~'.*{instance}.*', name!=''}}))"
    container_cpu_q = f"topk(5, sum by (name) (rate(container_cpu_usage_seconds_total{{instance=~'.*{instance}.*', name!=''}}[5m])) * 100)"
    container_write_q = f"topk(5, sum by (name) (rate(container_fs_writes_bytes_total{{instance=~'.*{instance}.*', name!=''}}[5m])) + 1)"
    
    docker_log_volume_q = f"sum by (container) (count_over_time({{job='docker', instance=~'.*{instance}.*}}[1h]))"
    systemd_log_volume_q = f"sum by (unit) (count_over_time({{job='systemd', instance=~'.*{instance}.*}}[1h]))"
    
    async with httpx.AsyncClient(timeout=12.0) as client:
        results = {}
        queries = {
            "c_mem": (f"{PROMETHEUS_URL}/api/v1/query", {"query": container_mem_q}),
            "c_cpu": (f"{PROMETHEUS_URL}/api/v1/query", {"query": container_cpu_q}),
            "c_write": (f"{PROMETHEUS_URL}/api/v1/query", {"query": container_write_q}),
            "docker_logs": (f"{LOKI_URL}/loki/api/v1/query", {"query": docker_log_volume_q}),
            "systemd_logs": (f"{LOKI_URL}/loki/api/v1/query", {"query": systemd_log_volume_q})
        }
        
        for name, (url, params) in queries.items():
            try:
                res = await client.get(url, params=params)
                if res.status_code == 200:
                    results[name] = res.json().get("data", {}).get("result", [])
                else:
                    results[name] = []
            except Exception as e:
                logger.error(f"Error calling {name}: {e}")
                results[name] = []
                
        cpu_lines = []
        for item in results["c_cpu"]:
            name = item.get("metric", {}).get("name", "unknown")
            val = round(float(item["value"][1]), 2)
            cpu_lines.append(f"- **`{name}`**: {val}% CPU core")
        cpu_report = "\n".join(cpu_lines) if cpu_lines else "- Không ghi nhận dữ liệu cAdvisor CPU."
        
        mem_lines = []
        for item in results["c_mem"]:
            name = item.get("metric", {}).get("name", "unknown")
            val_mb = round(float(item["value"][1]) / (1024**2), 2)
            mem_lines.append(f"- **`{name}`**: {val_mb} MB RAM")
        mem_report = "\n".join(mem_lines) if mem_lines else "- Không ghi nhận dữ liệu cAdvisor Memory."
        
        write_lines = []
        for item in results["c_write"]:
            name = item.get("metric", {}).get("name", "unknown")
            val_kb = round((float(item["value"][1]) - 1) / 1024, 2)
            if val_kb < 0: val_kb = 0.0
            write_lines.append(f"- **`{name}`**: {val_kb} KB/s ghi đĩa")
        write_report = "\n".join(write_lines) if write_lines else "- Không ghi nhận dữ liệu cAdvisor Disk Write."
        
        d_log_lines = []
        sorted_d_logs = sorted(results["docker_logs"], key=lambda x: float(x["value"][1]), reverse=True)[:5]
        for item in sorted_d_logs:
            container = item.get("metric", {}).get("container", "unknown")
            count = int(float(item["value"][1]))
            d_log_lines.append(f"- **`{container}`**: {count:,} dòng log/giờ")
        docker_log_report = "\n".join(d_log_lines) if d_log_lines else "- Không ghi nhận log docker nào trong 1 giờ qua."
        
        sys_log_lines = []
        sorted_sys_logs = sorted(results["systemd_logs"], key=lambda x: float(x["value"][1]), reverse=True)[:5]
        for item in sorted_sys_logs:
            unit = item.get("metric", {}).get("unit", "unknown")
            count = int(float(item["value"][1]))
            sys_log_lines.append(f"- **`{unit}`**: {count:,} dòng log/giờ")
        systemd_log_report = "\n".join(sys_log_lines) if sys_log_lines else "- Không ghi nhận log systemd nào trong 1 giờ qua."
        
        report = [
            f"## 🔍 Resource Consumer Analysis for Host: `{instance}`\n",
            f"### ⚙️ Top 5 Containers by CPU usage",
            cpu_report + "\n",
            f"### 🧠 Top 5 Containers by RAM usage",
            mem_report + "\n",
            f"### 💾 Top 5 Containers by Disk Write Activity",
            write_report + "\n",
            f"### 📝 Top 5 Docker Containers by Log Volume (Last 1 hour)",
            docker_log_report + "\n",
            f"### ⚙️ Top 5 Systemd Services by Log Volume (Last 1 hour)",
            systemd_log_report
        ]
        return "\n".join(report)

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
        logger.info("Starting MCP Server in SSE (HTTP) and Streamable HTTP modes on port 8000")
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.requests import Request
        from starlette.responses import Response
        
        class NoOpResponse(Response):
            async def __call__(self, scope, receive, send) -> None:
                pass

        # Get standard SSE and Streamable HTTP Starlette apps
        sse_app = mcp.sse_app()
        http_app = mcp.streamable_http_app()
        
        # Combine routes from both apps to support all network transport methods
        routes = []
        routes.extend(sse_app.routes)
        
        # Wrap the streamable http app route handler to be a Starlette request-response endpoint
        # to fix the official python-sdk bug where it registers an ASGI app as a Route endpoint
        try:
            http_asgi = http_app.routes[0].endpoint
            async def http_endpoint(request: Request) -> Response:
                await http_asgi(request.scope, request.receive, request._send)
                return NoOpResponse()
            routes.append(Route("/mcp", endpoint=http_endpoint, methods=["GET", "POST", "OPTIONS"]))
            logger.info("Added wrapped Route for /mcp")
        except Exception as e:
            logger.error(f"Failed to wrap /mcp route: {e}")
            routes.extend(http_app.routes)
        
        # Add a compatibility route: POST /sse -> sse.handle_post_message
        # This resolves issues with clients that ignore the event endpoint and POST directly to /sse
        try:
            # Route index 1 in sse_app is typically the Mount for self.settings.message_path
            handle_post_message = sse_app.routes[1].app
            async def post_message_endpoint(request: Request) -> Response:
                await handle_post_message(request.scope, request.receive, request._send)
                return NoOpResponse()
            routes.append(Route("/sse", endpoint=post_message_endpoint, methods=["POST", "OPTIONS"]))
            logger.info("Added compatibility route POST /sse -> handle_post_message")
        except Exception as e:
            logger.error(f"Failed to add compatibility route POST /sse: {e}")
            
        app = Starlette(debug=mcp.settings.debug, routes=routes, lifespan=http_app.router.lifespan_context)
        uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)
    else:
        logger.info("Starting MCP Server in Stdio mode")
        mcp.run("stdio")
