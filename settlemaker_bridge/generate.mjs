// Thin wrapper around settlemaker's generateSettlement, for Python to call
// as a subprocess. See docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md
// ("Architecture — the integration boundary").
//
// stdin:  JSON { burg: AzgaarBurgInput, seed: number }
// stdout: JSON { geojson, svg } -- settlemaker's own FeatureCollection and
//         themed SVG, unmodified except geojson.metadata.generated_at is
//         stripped -- it's a wall-clock timestamp, the one non-deterministic
//         field settlemaker itself documents, and this project's determinism
//         guarantee never persists or compares it.

import { generateSettlement } from "settlemaker";

function readStdin() {
  return new Promise((resolve, reject) => {
    const chunks = [];
    process.stdin.on("data", (chunk) => chunks.push(chunk));
    process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf-8")));
    process.stdin.on("error", reject);
  });
}

async function main() {
  const raw = await readStdin();
  const { burg, seed } = JSON.parse(raw);

  const result = generateSettlement(burg, { seed });
  const { geojson, svg } = result;
  if (geojson.metadata) {
    delete geojson.metadata.generated_at;
  }

  process.stdout.write(JSON.stringify({ geojson, svg }));
}

main().catch((err) => {
  process.stderr.write(String(err.stack || err) + "\n");
  process.exit(1);
});
