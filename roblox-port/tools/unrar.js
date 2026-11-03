// List or extract a RAR archive with node-unrar-js (pure WASM).
// Usage: node unrar.js <archive.rar> [outDir]   (no outDir = list only)
const path = require("path");
const fs = require("fs");
const { createExtractorFromFile } = require(path.join(__dirname, "..", "node-tools", "node_modules", "node-unrar-js"));

(async () => {
  const [archive, outDir] = process.argv.slice(2);
  if (!outDir) {
    const ex = await createExtractorFromFile({ filepath: archive, targetPath: "/nonexistent" });
    const list = ex.getFileList();
    let n = 0, total = 0;
    for (const h of list.fileHeaders) {
      n++;
      total += h.unpSize;
      console.log(`${h.flags.directory ? "D" : "F"} ${String(h.unpSize).padStart(10)}  ${h.name}`);
    }
    console.log(`-- ${n} entries, ${total} bytes unpacked`);
    return;
  }
  fs.mkdirSync(outDir, { recursive: true });
  const ex = await createExtractorFromFile({ filepath: archive, targetPath: outDir });
  const res = ex.extract();
  let n = 0;
  for (const f of res.files) n++;
  console.log(`extracted ${n} entries to ${outDir}`);
})().catch((e) => { console.error("FAILED:", e.message || e); process.exit(1); });
