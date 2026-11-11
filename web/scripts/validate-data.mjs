// Smoke-validates the extracted data package against the contract before the site is
// built: a representative file of each schema is checked with ajv (JSON Schema draft
// 2020-12), and every checked file must carry the data_version and a schema version
// listed in ../data-release.json. The full package is already validated by the exporter;
// this catches a corrupted download, a stale extraction or a pointer/schema mismatch.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const release = JSON.parse(
  fs.readFileSync(path.join(webRoot, "..", "data-release.json"), "utf-8"),
);
const schemasDir = path.join(webRoot, "..", "src", "atlas_da_lavoura", "serving", "schemas");
const dataDir = path.join(webRoot, "public", "data", release.data_version);

// One representative file per schema; globs pick the first match alphabetically.
const SMOKE = [
  ["catalog", "catalog.json"],
  ["municipalities", "municipalities.json"],
  ["analysis", "analysis.json"],
  ["method", "method.json"],
  ["explore", "explore/soybean/production_t.json"],
  ["place", "places/country.json"],
  ["place", "places/state/*.json"],
  ["place", "places/region/*.json"],
  ["topology", "geo/states.topo.json"],
  ["topology", "geo/municipalities.topo.json"],
  ["manifest", "manifest.json"],
];

function firstMatch(pattern) {
  if (!pattern.includes("*")) return path.join(dataDir, pattern);
  const directory = path.join(dataDir, path.dirname(pattern));
  const suffix = path.basename(pattern).replace("*", "");
  const name = fs
    .readdirSync(directory)
    .filter((entry) => entry.endsWith(suffix))
    .sort()[0];
  if (!name) throw new Error(`no file matches ${pattern}`);
  return path.join(directory, name);
}

function main() {
  const ajv = new Ajv2020({ allErrors: true });
  addFormats(ajv);
  ajv.addSchema(
    JSON.parse(fs.readFileSync(path.join(schemasDir, "common.schema.json"), "utf-8")),
    "common.schema.json",
  );
  const validators = new Map();
  const failures = [];
  for (const [schemaName, pattern] of SMOKE) {
    if (!validators.has(schemaName)) {
      const schema = JSON.parse(
        fs.readFileSync(path.join(schemasDir, `${schemaName}.schema.json`), "utf-8"),
      );
      validators.set(schemaName, ajv.compile(schema));
    }
    const file = firstMatch(pattern);
    const shown = path.relative(dataDir, file);
    const data = JSON.parse(fs.readFileSync(file, "utf-8"));
    const validate = validators.get(schemaName);
    if (!validate(data)) {
      failures.push(`${shown}: ${ajv.errorsText(validate.errors)}`);
      continue;
    }
    const meta = data.meta ?? {};
    if (meta.data_version !== release.data_version) {
      failures.push(`${shown}: data_version ${meta.data_version} != ${release.data_version}`);
    }
    const versionKey = `${meta.schema}/${meta.schema_version}`;
    if (meta.schema !== "manifest" && !release.schema_versions.includes(versionKey)) {
      failures.push(`${shown}: schema version ${versionKey} not in the pointer`);
    }
    console.log(`ok ${shown} (${schemaName})`);
  }
  if (failures.length > 0) {
    console.error("FAILED:\n  " + failures.join("\n  "));
    process.exit(1);
  }
  console.log("all smoke validations passed");
}

main();
