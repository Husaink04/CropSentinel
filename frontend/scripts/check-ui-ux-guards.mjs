import fs from "node:fs";
import path from "node:path";

const checks = [
  {
    file: path.join("src", "pages", "LiveView.jsx"),
    needles: ["RealtimeStatusBanner", "status={realtimeStatus}"],
  },
  {
    file: path.join("src", "pages", "RemoteAccess.jsx"),
    needles: ["RealtimeStatusBanner", "status={realtimeStatus}"],
  },
  {
    file: path.join("src", "pages", "Teams.jsx"),
    needles: ["PageStateView", "InlineBanner"],
  },
  {
    file: path.join("src", "pages", "TeamDashboard.jsx"),
    needles: ["PageStateView", "InlineBanner"],
  },
];

let failed = false;
for (const check of checks) {
  const abs = path.resolve(process.cwd(), check.file);
  const text = fs.readFileSync(abs, "utf8");
  for (const needle of check.needles) {
    if (!text.includes(needle)) {
      console.error(`[check-ui-ux-guards] Missing "${needle}" in ${check.file}`);
      failed = true;
    }
  }
}

if (failed) process.exit(1);
console.log("[check-ui-ux-guards] OK");
