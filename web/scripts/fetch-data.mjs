// Downloads the data package pinned by ../data-release.json, verifies its sha256 and size
// against the pointer, and extracts it into public/data/ (the tarball root is the data
// version, so the files land at public/data/<data_version>/...). The verified tarball is
// kept in .cache/<sha256>.tar.gz, so re-runs and CI cache restores skip the download.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const release = JSON.parse(
  fs.readFileSync(path.join(webRoot, "..", "data-release.json"), "utf-8"),
);
const cacheDir = path.join(webRoot, ".cache");
const tarball = path.join(cacheDir, `${release.sha256}.tar.gz`);
const dataDir = path.join(webRoot, "public", "data");
const target = path.join(dataDir, release.data_version);
// The package is ~10 MB; without a deadline a stalled connection would wait on undici's
// 5-minute header and body timeouts, and a slow trickle would never time out.
const DOWNLOAD_TIMEOUT_MS = 120_000;

function sha256(file) {
  return createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function verify(file) {
  const size = fs.statSync(file).size;
  if (size !== release.bytes) {
    throw new Error(`size mismatch: ${size} bytes, pointer says ${release.bytes}`);
  }
  const digest = sha256(file);
  if (digest !== release.sha256) {
    throw new Error(`sha256 mismatch: ${digest}, pointer says ${release.sha256}`);
  }
}

async function download() {
  console.log(`downloading ${release.asset_url}`);
  let body;
  try {
    const response = await fetch(release.asset_url, {
      signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error(`download failed: HTTP ${response.status}`);
    }
    body = Buffer.from(await response.arrayBuffer());
  } catch (error) {
    if (error?.name === "TimeoutError") {
      throw new Error(`download timed out after ${DOWNLOAD_TIMEOUT_MS / 1000} s`);
    }
    throw error;
  }
  fs.mkdirSync(cacheDir, { recursive: true });
  const temporary = `${tarball}.part`;
  fs.writeFileSync(temporary, body);
  fs.renameSync(temporary, tarball);
}

async function main() {
  const marker = path.join(target, "catalog.json");
  if (fs.existsSync(marker)) {
    console.log(`data ${release.data_version} already extracted, nothing to do`);
    return;
  }
  if (fs.existsSync(tarball)) {
    console.log(`using cached ${path.basename(tarball)}`);
  } else {
    await download();
  }
  try {
    verify(tarball);
  } catch (error) {
    fs.rmSync(tarball, { force: true });
    throw error;
  }
  fs.rmSync(target, { recursive: true, force: true });
  fs.mkdirSync(dataDir, { recursive: true });
  execFileSync("tar", ["-xzf", tarball, "-C", dataDir]);
  if (!fs.existsSync(marker)) {
    throw new Error("extraction did not produce catalog.json");
  }
  console.log(`verified sha256 ${release.sha256.slice(0, 12)}… and extracted to ${target}`);
}

main().catch((error) => {
  console.error(String(error));
  process.exit(1);
});
