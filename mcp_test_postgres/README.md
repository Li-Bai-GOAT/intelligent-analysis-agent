# DataAgent PostgreSQL MCP test source

This directory starts an isolated PostgreSQL 16 container with generated sales
data. It is not connected to the application database or an intranet database.

The only account intended for MCP use is `dataagent_mcp_ro`. It can connect to
`dataagent_mcp_test` and read `agent_views.monthly_sales_summary`; it cannot
read `raw_data` or modify the database. The container uses PostgreSQL `trust`
authentication because it contains only generated test data and is bound to
`127.0.0.1:55578`. Do not reuse this configuration outside local testing.

Start it from the repository root:

```powershell
docker compose -f .\mcp_test_postgres\docker-compose.yml up -d
```

The sandbox reaches it at:

```text
postgresql://dataagent_mcp_ro@host.docker.internal:55578/dataagent_mcp_test
```

Run the MCP smoke test after building the sandbox image:

```powershell
docker run --rm -i `
  -e PGSQL_MCP_CONNECTION_STRING=postgresql://dataagent_mcp_ro@host.docker.internal:55578/dataagent_mcp_test `
  -v "${PWD}\mcp_test_postgres\verify_postgres_mcp.mjs:/tmp/verify_postgres_mcp.mjs:ro" `
  agentscope/runtime-sandbox-data_analysis:latest `
  node /tmp/verify_postgres_mcp.mjs
```

To remove only this disposable test source after development:

```powershell
docker compose -f .\mcp_test_postgres\docker-compose.yml down -v
```
