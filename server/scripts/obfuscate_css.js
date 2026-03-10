#!/usr/bin/env node
/**
 * CSS obfuscation script — runs inside Docker builder stage after pnpm build.
 *
 * Usage: node obfuscate_css.js <dist_dir> <page_hash>
 *
 * What it does:
 *   1. Collects all CSS from dist/_astro/*.css
 *   2. Renames classes to deterministic hashes: _sha256(name+pageHash)[:6]
 *   3. Applies renaming to HTML files (class="..." attributes)
 *   4. Saves CSS bundle to <parent_of_dist>/css_bundle.txt
 *   5. Removes .css files from dist (CSS delivered via fingerprint API)
 *   6. Removes <link rel="stylesheet"> tags from HTML
 */

'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const distDir = process.argv[2];
const pageHash = process.argv[3];

if (!distDir || !pageHash) {
  console.error('Usage: node obfuscate_css.js <dist_dir> <page_hash>');
  process.exit(1);
}

if (!fs.existsSync(distDir)) {
  console.error(`dist dir not found: ${distDir}`);
  process.exit(1);
}

// ── File discovery ────────────────────────────────────────────────────────────

function findFiles(dir, ext) {
  const results = [];
  try {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        results.push(...findFiles(fullPath, ext));
      } else if (entry.isFile() && entry.name.endsWith(ext)) {
        results.push(fullPath);
      }
    }
  } catch (_) {}
  return results;
}

const cssFiles = findFiles(distDir, '.css');
const htmlFiles = findFiles(distDir, '.html');

if (cssFiles.length === 0) {
  console.log('No CSS files found — skipping obfuscation');
  // Write empty bundle so deploy script doesn't fail
  const bundlePath = path.join(path.dirname(distDir), 'css_bundle.txt');
  fs.writeFileSync(bundlePath, '', 'utf8');
  process.exit(0);
}

// ── Collect CSS ───────────────────────────────────────────────────────────────

const cssBundle = cssFiles.map(f => fs.readFileSync(f, 'utf8')).join('\n');

// ── Extract class names ───────────────────────────────────────────────────────

const classNames = new Set();
const classRegex = /\.([a-zA-Z][a-zA-Z0-9_-]*)/g;
let match;
while ((match = classRegex.exec(cssBundle)) !== null) {
  classNames.add(match[1]);
}

// ── Build obfuscation map ─────────────────────────────────────────────────────

function obfuscateName(name) {
  const hash = crypto
    .createHash('sha256')
    .update(name + pageHash)
    .digest('hex')
    .slice(0, 6);
  return '_' + hash;
}

const classMap = {};
for (const name of classNames) {
  classMap[name] = obfuscateName(name);
}

// ── Obfuscate CSS ─────────────────────────────────────────────────────────────

// Replace .className selector occurrences (not inside strings or comments)
let obfuscatedCss = cssBundle;
for (const [original, obfuscated] of Object.entries(classMap)) {
  // Match class selector followed by whitespace, comma, {, :, [, ., +, ~, >
  const pattern = new RegExp(
    `\\.${original.replace(/[-[\]{}()*+?.,\\^$|#\s]/g, '\\$&')}(?=[\\s,{:#\\[.+~>)])`,
    'g'
  );
  obfuscatedCss = obfuscatedCss.replace(pattern, '.' + obfuscated);
}

// ── Save CSS bundle (obfuscated) ──────────────────────────────────────────────

const bundlePath = path.join(path.dirname(distDir), 'css_bundle.txt');
fs.writeFileSync(bundlePath, obfuscatedCss, 'utf8');

// ── Patch HTML files ──────────────────────────────────────────────────────────

for (const htmlFile of htmlFiles) {
  let html = fs.readFileSync(htmlFile, 'utf8');

  // Rename classes in class="..." attributes (handles space-separated lists)
  html = html.replace(/class="([^"]*)"/g, (_match, classes) => {
    const renamed = classes
      .split(/\s+/)
      .map(c => classMap[c] || c)
      .join(' ');
    return `class="${renamed}"`;
  });

  // Remove <link rel="stylesheet" ...> tags (CSS served via fingerprint API)
  html = html.replace(/<link[^>]+rel=["']stylesheet["'][^>]*\/?>/gi, '');
  html = html.replace(/<link[^>]+href=[^>]+\.css[^>]*\/?>/gi, '');

  fs.writeFileSync(htmlFile, html, 'utf8');
}

// ── Remove CSS files from dist ────────────────────────────────────────────────

for (const cssFile of cssFiles) {
  try { fs.unlinkSync(cssFile); } catch (_) {}
}

console.log(
  `Obfuscated ${classNames.size} classes, ` +
  `patched ${htmlFiles.length} HTML files, ` +
  `removed ${cssFiles.length} CSS files`
);
