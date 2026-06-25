## 🏛️ SƠ ĐỒ DÒNG CHẢY DỮ LIỆU TỰ TRỊ (PRODUCTION TOPOLOGY)

```jsx
                        ┌────────────────────────────────────────────┐
                        │              DEV EXPERIENCE                 │
                        │                                            │
                        │  - Claude CLI                             │
                        │  - Cursor IDE                            │
                        │  - VSCode MCP Extension                  │
                        │                                            │
                        │  "Why is service failing?"              │
                        │            ↓                              │
                        └──────────────┬─────────────────────────────┘
                                       │ MCP (Model Context Protocol)
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           AI OBSERVABILITY LAYER                         │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │                 MCP SERVER (CORE INTELLIGENCE)                   │   │
│   │                                                                  │   │
│   │  Tools exposed to LLM:                                          │   │
│   │   • query_logs()  → Loki (LogQL)                                │   │
│   │   • query_metrics() → Prometheus/Mimir                         │   │
│   │   • trace_incident() → correlation engine                      │   │
│   │   • summarize_logs() → LLM (Claude/OpenAI)                     │   │
│   │   • detect_anomaly() → time-series + log correlation           │   │
│   │   • explain_root_cause() → AI RCA engine                       │   │
│   │                                                                  │   │
│   │  Optional: Vector DB (Qdrant / pgvector)                      │   │
│   │  → semantic log search                                         │   │
│   └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
                                       │
                                       │ LogQL / PromQL / OTLP query
                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       CENTRAL OBSERVABILITY STACK                       │
│                                                                          │
│   ┌───────────────┐     ┌───────────────┐     ┌────────────────────┐   │
│   │   LOKI        │     │ PROMETHEUS    │     │   GRAFANA          │   │
│   │ Logs storage  │     │ Metrics TSDB  │     │ Dashboards         │   │
│   │               │     │               │     │ + Alerting         │   │
│   └──────┬────────┘     └──────┬────────┘     └─────────┬──────────┘   │
│          │                     │                        │                │
│          │ logs               │ metrics               │ UI             │
│          ▼                     ▼                        ▼                │
│   ┌──────────────────────────────────────────────────────────────┐      │
│   │ Alertmanager (optional but production-ready)                 │      │
│   └──────────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────────┘
                                       ▲
                                       │ remote_write / push
                                       │ logs / metrics
┌──────────────────────────────────────────────────────────────────────────┐
│                              EDGE LAYER                                 │
│                        (ALL NODES / FACTORY / VM)                      │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────┐      │
│   │                  GRAFANA ALLOY (AGENT)                      │      │
│   │                                                            │      │
│   │  METRICS:                                                 │      │
│   │   • node CPU / RAM / Disk                                 │      │
│   │   • Docker metrics                                        │      │
│   │   • container stats                                       │      │
│   │                                                            │      │
│   │  LOGS:                                                    │      │
│   │   • /var/log/*                                            │      │
│   │   • journald                                              │      │
│   │   • docker containers logs                                │      │
│   │                                                            │      │
│   │  PROCESSING:                                              │      │
│   │   • parsing JSON logs                                     │      │
│   │   • filtering noise                                       │      │
│   │   • labeling (service, env, node)                         │      │
│   │                                                            │      │
│   │  EXPORT:                                                  │      │
│   │   • Loki (logs push)                                      │      │
│   │   • Prometheus remote_write                              │      │
│   └──────────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────────┘
```