import { createRequire as __createRequire } from 'node:module';
import { fileURLToPath as __fileURLToPath } from 'node:url';
import { dirname as __dirname_ } from 'node:path';
const require = __createRequire(import.meta.url);
const __filename = __fileURLToPath(import.meta.url);
const __dirname = __dirname_(__filename);
import {
  require_ms
} from "./chunk-CO5D46AG.js";
import {
  __toESM
} from "./chunk-TZ2YI2VH.js";

// src/util/time-utils.ts
var import_ms = __toESM(require_ms(), 1);
function parseTimeFlag(input) {
  const milliseconds = (0, import_ms.default)(input);
  if (milliseconds !== void 0) {
    return new Date(Date.now() - milliseconds);
  }
  const date = new Date(input);
  if (isNaN(date.getTime())) {
    throw new Error(
      `Invalid time format "${input}". Use relative (1h, 30m, 2d, 1w) or ISO 8601 datetime.`
    );
  }
  return date;
}
function resolveTimeRange(since = "1h", until) {
  const startTime = parseTimeFlag(since);
  const endTime = until ? parseTimeFlag(until) : /* @__PURE__ */ new Date();
  return { startTime, endTime };
}

export {
  parseTimeFlag,
  resolveTimeRange
};
