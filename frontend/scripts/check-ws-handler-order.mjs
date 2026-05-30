import fs from "node:fs";
import path from "node:path";

const checks = [
  {
    file: path.join("src", "features", "sessions", "sessionShared.js"),
    callbackNeedle: "useWsListener(useCallback((msg) => {",
    listenerNeedle: "useWsListener(useCallback((msg) => {",
    mustContain: [
      "const { type, machine_id, session_id } = msg",
      "const currentId = selectedRef.current",
    ],
  },
  {
    file: path.join("src", "pages", "LiveView.jsx"),
    mustContain: [
      "useWebRtcSession({",
      "sessionKind: 'live'",
      "useSessionMachineDirectory(",
    ],
  },
  {
    file: path.join("src", "pages", "RemoteAccess.jsx"),
    mustContain: [
      "useWebRtcSession({",
      "sessionKind: 'remote'",
      "useSessionMachineDirectory(",
    ],
  },
];

let failed = false;
for (const c of checks) {
  const abs = path.resolve(process.cwd(), c.file);
  const content = fs.readFileSync(abs, "utf8");

  for (const needle of c.mustContain || []) {
    if (!content.includes(needle)) {
      console.error(`[check-ws-handler-order] Missing required marker "${needle}" in ${c.file}`);
      failed = true;
    }
  }

  if (c.callbackNeedle && c.listenerNeedle) {
    const cbIdx = content.indexOf(c.callbackNeedle);
    const wsIdx = content.indexOf(c.listenerNeedle);
    if (cbIdx === -1 || wsIdx === -1) {
      console.error(`[check-ws-handler-order] Missing marker in ${c.file}`);
      failed = true;
      continue;
    }
    if (cbIdx > wsIdx) {
      console.error(
        `[check-ws-handler-order] Invalid declaration order in ${c.file}: callback is declared after useWsListener(...)`,
      );
      failed = true;
      continue;
    }
  }

  console.log(`[check-ws-handler-order] OK: ${c.file}`);
}

if (failed) process.exit(1);
