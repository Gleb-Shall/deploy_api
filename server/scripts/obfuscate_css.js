#!/usr/bin/env node
/**
 * CSS obfuscation script — runs inside Docker builder stage after pnpm build.
 *
 * Usage: node obfuscate_css.js <dist_dir> <page_hash>
 *
 * What it does:
 *   1. Collects CSS from both external files (dist/_astro/*.css) AND
 *      inline <style> tags in HTML (Astro often inlines CSS, no external files)
 *   2. Renames class selectors to deterministic hashes: _sha256(name+hash)[:6]
 *   3. Applies renaming to HTML class="..." attributes
 *   4. Removes <style> tags from HTML (CSS delivered via fingerprint API)
 *   5. Removes <link rel="stylesheet"> tags from HTML
 *   6. Removes .css files from dist
 *   7. Saves obfuscated CSS bundle to <parent_of_dist>/css_bundle.txt
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

// ── Collect CSS from external files ──────────────────────────────────────────

const externalCss = cssFiles.map(f => fs.readFileSync(f, 'utf8')).join('\n');

// ── Collect CSS from inline <style> tags in HTML ──────────────────────────────
// Astro often inlines all CSS directly into <style> tags instead of
// generating external .css files. We need to handle both cases.

const STYLE_TAG_RE = /<style[^>]*>([\s\S]*?)<\/style>/gi;

let inlineCss = '';
for (const htmlFile of htmlFiles) {
  const html = fs.readFileSync(htmlFile, 'utf8');
  let m;
  STYLE_TAG_RE.lastIndex = 0;
  while ((m = STYLE_TAG_RE.exec(html)) !== null) {
    inlineCss += m[1] + '\n';
  }
}

const allCss = externalCss + '\n' + inlineCss;

if (!allCss.trim()) {
  console.log('No CSS found (external or inline) — writing empty bundle');
  const bundlePath = path.join(path.dirname(distDir), 'css_bundle.txt');
  fs.writeFileSync(bundlePath, '', 'utf8');
  process.exit(0);
}

// ── Build class name obfuscation map ─────────────────────────────────────────

function obfuscateName(name) {
  const hash = crypto
    .createHash('sha256')
    .update(name + pageHash)
    .digest('hex')
    .slice(0, 6);
  return '_' + hash;
}

const classNames = new Set();
const classRegex = /\.([a-zA-Z][a-zA-Z0-9_-]*)/g;
let m;
while ((m = classRegex.exec(allCss)) !== null) {
  classNames.add(m[1]);
}

const classMap = {};
for (const name of classNames) {
  classMap[name] = obfuscateName(name);
}

// ── Obfuscate CSS ─────────────────────────────────────────────────────────────

function obfuscateCss(css) {
  let result = css;
  for (const [original, obfuscated] of Object.entries(classMap)) {
    const pattern = new RegExp(
      `\\.${original.replace(/[-[\]{}()*+?.,\\^$|#\s]/g, '\\$&')}(?=[\\s,{:#\\[.+~>)])`,
      'g'
    );
    result = result.replace(pattern, '.' + obfuscated);
  }
  return result;
}

const obfuscatedCss = obfuscateCss(allCss);

// ── Save CSS bundle ───────────────────────────────────────────────────────────

const bundlePath = path.join(path.dirname(distDir), 'css_bundle.txt');
fs.writeFileSync(bundlePath, obfuscatedCss, 'utf8');

// ── Patch HTML files ──────────────────────────────────────────────────────────

for (const htmlFile of htmlFiles) {
  let html = fs.readFileSync(htmlFile, 'utf8');

  // Rename classes in class="..." attributes
  html = html.replace(/class="([^"]*)"/g, (_match, classes) => {
    const renamed = classes
      .split(/\s+/)
      .filter(Boolean)
      .map(c => classMap[c] || c)
      .join(' ');
    return `class="${renamed}"`;
  });

  // Remove inline <style> tags (CSS moved to encrypted bundle), including empty ones
  html = html.replace(/<style[^>]*>[\s\S]*?<\/style>\s*/gi, '');

  // Remove <link rel="stylesheet"> tags
  html = html.replace(/<link[^>]+rel=["']stylesheet["'][^>]*\/?>/gi, '');
  html = html.replace(/<link[^>]+href=[^>]+\.css[^>]*\/?>/gi, '');

  fs.writeFileSync(htmlFile, html, 'utf8');
}

// ── Remove CSS files from dist ────────────────────────────────────────────────

for (const cssFile of cssFiles) {
  try { fs.unlinkSync(cssFile); } catch (_) {}
}

console.log(
  `Collected ${classNames.size} classes (${cssFiles.length} external + inline styles), ` +
  `patched ${htmlFiles.length} HTML files, ` +
  `bundle: ${obfuscatedCss.length} bytes`
);
