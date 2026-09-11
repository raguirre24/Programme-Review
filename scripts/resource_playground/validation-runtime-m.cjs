"use strict";

// Microsoft parser syntax validation; no Power Query execution or source access.
const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const directory = path.resolve(process.argv[2]);
  const parser = require(directory);
  const input = JSON.parse(fs.readFileSync(0, "utf8").replace(/^\uFEFF/, ""));
  const failures = [];
  for (const query of input.queries) {
    const result = await parser.TaskUtils.tryLexParse(parser.DefaultSettings, query.expression);
    if (parser.TaskUtils.isError(result)) {
      failures.push({ name: query.name, error: result.error?.message || String(result.error) });
    }
  }
  process.stdout.write(JSON.stringify({
    result: failures.length ? "FAIL" : "PASS",
    expressions: input.queries.length,
    parserVersion: require(path.join(directory, "package.json")).version,
    failures,
    scope: "Syntax only; M expressions are not executed.",
  }));
  if (failures.length) process.exitCode = 1;
}

main().catch(error => {
  process.stderr.write(error.message + "\n");
  process.exitCode = 1;
});
