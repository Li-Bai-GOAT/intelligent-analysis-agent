import { spawn } from "node:child_process";
import readline from "node:readline";

const child = spawn("postgres-mcp", ["run"], {
  env: process.env,
  stdio: ["pipe", "pipe", "pipe"],
});

const pending = new Map();
let nextId = 1;

const stderr = readline.createInterface({ input: child.stderr });
stderr.on("line", (line) => process.stderr.write(`[postgres-mcp] ${line}\n`));

const stdout = readline.createInterface({ input: child.stdout });
stdout.on("line", (line) => {
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    return;
  }
  const resolve = pending.get(message.id);
  if (resolve) {
    pending.delete(message.id);
    resolve(message);
  }
});

function request(method, params = {}) {
  const id = nextId++;
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id, method, params })}\n`);
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Timed out waiting for ${method}`));
    }, 20_000);
    pending.set(id, (message) => {
      clearTimeout(timeout);
      if (message.error) reject(new Error(`${method}: ${message.error.message}`));
      else resolve(message.result);
    });
  });
}

function toolText(result) {
  return JSON.stringify(result.content ?? []);
}

try {
  await request("initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "dataagent-mcp-smoke-test", version: "1.0.0" },
  });
  child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" })}\n`);

  const listed = await request("tools/list");
  const queryTool = listed.tools.find((tool) => tool.name === "pgsql_query");
  if (!queryTool) throw new Error(`pgsql_query is unavailable: ${listed.tools.map((tool) => tool.name).join(", ")}`);

  const connectTool = listed.tools.find((tool) => tool.name === "pgsql_connect");
  if (!connectTool) throw new Error("pgsql_connect is unavailable");
  const connectProperties = connectTool.inputSchema?.properties ?? {};
  const profileList = await request("tools/call", {
    name: "pgsql_list_connection_profiles",
    arguments: {},
  });
  if (profileList.isError) throw new Error(JSON.stringify(profileList.content));
  const profileText = (profileList.content ?? [])
    .filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("\n");
  const profileId = profileText.match(/[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}/i)?.[0];
  if (!profileId) throw new Error(`Unable to read the default profile ID: ${profileText}`);

  const connectArgument = connectProperties.profileId
    ? { profileId }
    : connectProperties.connectionId
      ? { connectionId: profileId }
      : connectProperties.profile
        ? { profile: "default" }
        : connectProperties.profileName
          ? { profileName: "default" }
          : null;
  if (!connectArgument) throw new Error(`Unsupported pgsql_connect schema: ${JSON.stringify(connectTool.inputSchema)}`);
  const connected = await request("tools/call", { name: "pgsql_connect", arguments: connectArgument });
  if (connected.isError) throw new Error(JSON.stringify(connected.content));
  const connectedText = (connected.content ?? [])
    .filter((item) => item.type === "text")
    .map((item) => item.text)
    .join("\n");
  const connectionId = connectedText.match(/pgsql\/[0-9a-f-]+\/[A-Za-z0-9_-]+/i)?.[0];
  if (!connectionId) throw new Error(`Unable to read the active connection ID: ${connectedText}`);

  const properties = queryTool.inputSchema?.properties ?? {};
  const queryArgument = properties.sql ? "sql" : properties.query ? "query" : null;
  if (!queryArgument) throw new Error("pgsql_query does not expose an sql/query argument");

  const result = await request("tools/call", {
    name: "pgsql_query",
    arguments: {
      connectionId,
      [queryArgument]: "SELECT region, SUM(revenue) AS revenue FROM agent_views.monthly_sales_summary GROUP BY region ORDER BY region",
    },
  });
  if (result.isError) throw new Error(JSON.stringify(result.content));
  const output = toolText(result);
  if (!output.includes("East") || !output.includes("West")) {
    throw new Error(`Expected seeded rows in PostgreSQL MCP result: ${output}`);
  }

  const rawSchemaResult = await request("tools/call", {
    name: "pgsql_query",
    arguments: {
      connectionId,
      [queryArgument]: "SELECT * FROM raw_data.monthly_sales",
    },
  });
  if (!toolText(rawSchemaResult).includes("permission denied")) {
    throw new Error(`Raw schema should be blocked for the MCP role: ${toolText(rawSchemaResult)}`);
  }

  const writeAttempt = await request("tools/call", {
    name: "pgsql_query",
    arguments: {
      connectionId,
      [queryArgument]: "INSERT INTO raw_data.monthly_sales (month_start, region, revenue, orders) VALUES ('2026-04-01', 'East', 1, 1)",
    },
  });
  const writeOutput = toolText(writeAttempt).toLowerCase();
  if (!writeAttempt.isError && !writeOutput.includes("read-only") && !writeOutput.includes("permission denied") && !writeOutput.includes("only select") && !writeOutput.includes("errormessage")) {
    throw new Error(`Write attempt unexpectedly succeeded: ${writeOutput}`);
  }
  console.log("PostgreSQL MCP smoke test passed: read-only aggregate query returned seeded rows.");
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  child.kill();
}

// postgres-mcp performs asynchronous telemetry cleanup after SIGTERM.  This
// test is deliberately disposable, so terminate the helper process rather
// than keeping Docker/CI alive for that best-effort cleanup.
process.exit(process.exitCode ?? 0);
