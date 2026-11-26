import * as opaque from "@serenity-kit/opaque";
import { readFileSync } from "node:fs";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";

await opaque.ready;
const serverSetup = process.env.OPAQUE_SERVER_SETUP;
const isDaemon = process.argv.includes("--daemon");

async function handleRequest(request) {
  const { id, operation, ...parameters } = request;
  let result;
  try {
    switch (operation) {
      case "register":
        result = opaque.server.createRegistrationResponse({ serverSetup, ...parameters });
        break;
      case "login":
        result = opaque.server.startLogin({
          ...parameters, serverSetup,
          registrationRecord: parameters.registrationRecord ?? undefined,
        });
        break;
      case "checkRecord": {
        const { startLoginRequest } = opaque.client.startLogin({ password: "record validation" });
        opaque.server.startLogin({ serverSetup, ...parameters, startLoginRequest });
        result = true;
        break;
      }
      case "finish":
        result = Boolean(opaque.server.finishLogin(parameters)?.sessionKey);
        break;
      default:
        throw new Error(`Unknown operation: ${operation}`);
    }
  } catch {
    result = null;
  }
  return { id, result: result ?? null };
}

if (isDaemon) {
  const rl = createInterface({ input: stdin, output: stdout, terminal: false });
  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const request = JSON.parse(line);
      const response = await handleRequest(request);
      stdout.write(JSON.stringify(response) + "\n");
    } catch (e) {
      stdout.write(JSON.stringify({ id: request?.id ?? null, error: "Invalid request" }) + "\n");
    }
  }
} else {
  const { operation, ...parameters } = JSON.parse(readFileSync(0, "utf8"));
  const result = await handleRequest({ id: 1, operation, ...parameters });
  stdout.write(JSON.stringify(result.result ?? null));
}
