import * as opaque from "@serenity-kit/opaque";
import { readFileSync } from "node:fs";

await opaque.ready;
const { operation, ...parameters } = JSON.parse(readFileSync(0, "utf8"));
const serverSetup = process.env.OPAQUE_SERVER_SETUP;
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
  }
} catch {
  result = null;
}
process.stdout.write(JSON.stringify(result || null));
