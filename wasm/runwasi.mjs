// Node harness: run a SWMM wasm32-wasi engine on an .inp, like runswmm.
import { readFile } from 'node:fs/promises';
import { WASI } from 'node:wasi';
import path from 'node:path';
const [wasmPath, inp, rpt, out] = process.argv.slice(2);
const dir = path.dirname(path.resolve(inp));
const wasi = new WASI({ version: 'preview1', args: ['swmm', path.basename(inp), path.basename(rpt), path.basename(out)],
  preopens: { '.': dir }, returnOnExit: true });
const mod = await WebAssembly.compile(await readFile(wasmPath));
const inst = await WebAssembly.instantiate(mod, wasi.getImportObject());
process.chdir(dir);
const rc = wasi.start(inst);
process.exit(rc);
