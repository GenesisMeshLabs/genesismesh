import { Container, getContainer } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

export class GenesisMeshNAContainer extends Container {
  defaultPort = 8443;
  sleepAfter = "10m";
  envVars = {
    SERVICE_ROLE: "na",
    PORT: "8443",
    WEB_CONCURRENCY: "1",
    GENESIS_FILE:
      env.GENESIS_FILE || "examples/official-operators/epical-na/genesis.signed.json",
    GENESIS_JSON: env.GENESIS_JSON || "",
    NA_PRIVATE_KEY_FILE: "/tmp/na.key",
    NA_PRIVATE_KEY: env.NA_PRIVATE_KEY || "",
    NA_KEY_ID: env.NA_KEY_ID || "na-2025-q1",
    OPERATOR_PUBLIC_KEYS_JSON: env.OPERATOR_PUBLIC_KEYS_JSON || "{}",
    DB_PATH: "/tmp/genesis_mesh_na.db",
  };

  onStart() {
    console.log("Genesis Mesh Network Authority container started");
  }

  onStop({ exitCode, reason }) {
    console.log("Genesis Mesh Network Authority container stopped", {
      exitCode,
      reason,
    });
  }

  onError(error) {
    console.error("Genesis Mesh Network Authority container error", error);
    throw error;
  }
}

export default {
  async fetch(request, workerEnv) {
    const url = new URL(request.url);

    if (url.pathname === "/cf-healthz") {
      return Response.json({
        ok: Boolean(workerEnv.NA_PRIVATE_KEY && workerEnv.GENESIS_JSON),
        service: "genesismesh-na-worker",
        testCase: "EPICAL-NA",
        hasGenesisJson: Boolean(workerEnv.GENESIS_JSON),
        hasNaPrivateKey: Boolean(workerEnv.NA_PRIVATE_KEY),
      });
    }

    if (url.pathname === "/favicon.ico") {
      return new Response(null, { status: 204 });
    }

    if (!workerEnv.NA_PRIVATE_KEY || !workerEnv.GENESIS_JSON) {
      return Response.json(
        {
          error: "missing_cloudflare_secrets",
          message:
            "Set Worker secrets NA_PRIVATE_KEY and GENESIS_JSON before starting the EPICAL-NA container.",
          requiredSecrets: ["NA_PRIVATE_KEY", "GENESIS_JSON"],
        },
        { status: 503 },
      );
    }

    const container = getContainer(workerEnv.GENESIS_MESH_NA, "epical-na");
    return container.fetch(request);
  },
};
