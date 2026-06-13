#!/usr/bin/env node

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import vm from "node:vm";

const RAW_BASE =
  "https://raw.githubusercontent.com/Jakubantalik/transitions.dev/main";
const API_BASE = "https://api.github.com/repos/Jakubantalik/transitions.dev";
const DEFAULT_SOURCE = `${RAW_BASE}/index.html`;

const FILE_MAP = {
  p4: "01-card-resize.md",
  p9: "02-number-pop-in.md",
  p1: "03-notification-badge.md",
  p6: "04-text-states-swap.md",
  p2: "05-menu-dropdown.md",
  p7: "06-modal.md",
  p3: "07-panel-reveal.md",
  p8: "08-page-side-by-side.md",
  p5: "09-icon-swap.md",
  p10: "10-success-check.md",
  p11: "11-avatar-group-hover.md",
  p12: "12-error-state-shake.md",
  p13: "13-input-clear-dissolve.md",
  p14: "14-skeleton-reveal.md",
  p15: "15-shimmer-text.md",
  p16: "16-tabs-sliding.md",
  p17: "17-tooltip.md",
  p18: "18-texts-reveal.md",
  "tok-duration": "motion-token-duration.md",
  "tok-easing": "motion-token-easing.md",
  "tok-distance": "motion-token-distance.md",
  "tok-blur": "motion-token-blur.md",
  "tok-scale": "motion-token-scale.md",
};

function parseArgs(argv) {
  const args = {
    source: DEFAULT_SOURCE,
    format: "json",
    check: false,
    outDir: null,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--source") args.source = argv[++i];
    else if (arg === "--format") args.format = argv[++i];
    else if (arg === "--check") args.check = true;
    else if (arg === "--out-dir") args.outDir = argv[++i];
    else if (arg === "-h" || arg === "--help") args.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }

  return args;
}

function usage() {
  return `Usage:
  node extract-transitions-dev.mjs --format json
  node extract-transitions-dev.mjs --format markdown
  node extract-transitions-dev.mjs --out-dir ./references/generated
  node extract-transitions-dev.mjs --check

Options:
  --source <url>       Source index.html URL. Defaults to GitHub raw main.
  --format <format>    json or markdown. Defaults to json.
  --out-dir <path>     Write source-backed reference files into a directory.
  --check              Only print upstream status, dependencies, and license.`;
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: { "user-agent": "Maroun-Stack-Transitions-Extractor" },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status}`);
  }
  return response.text();
}

async function fetchJson(url) {
  const response = await fetch(url, {
    headers: {
      "accept": "application/vnd.github+json",
      "user-agent": "Maroun-Stack-Transitions-Extractor",
    },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}: ${response.status}`);
  }
  return response.json();
}

function decodeHtml(value) {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'");
}

function extractObjectLiteral(source, marker) {
  const markerIndex = source.indexOf(marker);
  if (markerIndex === -1) {
    throw new Error(`Marker not found: ${marker}`);
  }

  const open = source.indexOf("{", markerIndex);
  let depth = 0;
  let inString = null;
  let escaped = false;

  for (let i = open; i < source.length; i += 1) {
    const char = source[i];

    if (inString) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (char === "\\") {
        escaped = true;
        continue;
      }
      if (char === inString) inString = null;
      continue;
    }

    if (char === '"' || char === "'" || char === "`") {
      inString = char;
      continue;
    }

    if (char === "{") depth += 1;
    else if (char === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(open, i + 1);
    }
  }

  throw new Error(`Unbalanced braces after marker: ${marker}`);
}

function parseRootVariables(html) {
  const rootMatch = html.match(/:root\s*\{([\s\S]*?)\n\s*\}/);
  if (!rootMatch) throw new Error("No :root block found");

  const variables = {};
  const declarationPattern = /(--[a-z0-9-]+)\s*:\s*([^;]+);/gi;
  let match;

  while ((match = declarationPattern.exec(rootMatch[1])) !== null) {
    variables[match[1].trim()] = match[2].trim().replace(/\s+/g, " ");
  }

  return variables;
}

function renderRootCss(variables) {
  const declarations = Object.entries(variables)
    .map(([name, value]) => `  ${name}: ${value};`)
    .join("\n");

  return `/* Transitions.dev root motion variables. */\n:root {\n${declarations}\n}\n`;
}

function resolveVar(value, variables, seen = new Set()) {
  const varMatch = value.match(/^var\((--[a-z0-9-]+)\)$/i);
  if (!varMatch) return value;

  const key = varMatch[1];
  if (seen.has(key)) return value;
  if (!variables[key]) return value;

  seen.add(key);
  return resolveVar(variables[key], variables, seen);
}

function parseTemplates(html) {
  const objectLiteral = extractObjectLiteral(html, "var PROTO_TEMPLATES =");
  const sandbox = { result: null };
  vm.createContext(sandbox);
  vm.runInContext(`result = ${objectLiteral};`, sandbox);
  return sandbox.result;
}

function parseCards(html) {
  const cardPattern =
    /<div class="card-title">([^<]+)<\/div>\s*<div class="card-subtitle">([^<]+)<\/div>[\s\S]*?data-copy-key="([^"]+)"/g;
  const cards = [];
  let match;

  while ((match = cardPattern.exec(html)) !== null) {
    cards.push({
      key: decodeHtml(match[3]),
      title: decodeHtml(match[1]),
      subtitle: decodeHtml(match[2]),
    });
  }

  return cards;
}

function parseReactTemplates(html) {
  const scriptPattern =
    /<script type="text\/plain" data-react-key="([^"]+)">([\s\S]*?)<\/script>/g;
  const templates = {};
  let match;

  while ((match = scriptPattern.exec(html)) !== null) {
    templates[decodeHtml(match[1])] = decodeHtml(match[2]).trimEnd() + "\n";
  }

  return templates;
}

function buildCssSnippet(template, variables) {
  const parts = [`/* Transitions.dev - ${template.name} */`];

  if (template.usage) {
    parts.push(`/*\n  Usage:\n${template.usage}\n*/`);
  }

  if (template.vars?.length) {
    const rootLines = template.vars
      .map(([localName, sourceName]) => {
        const value = variables[sourceName] || "";
        return `  ${localName}: ${resolveVar(value, variables)};`;
      })
      .join("\n");
    parts.push(`:root {\n${rootLines}\n}`);
  }

  parts.push(template.css);
  return parts.join("\n\n");
}

async function upstreamStatus() {
  const [repo, commit, pkg] = await Promise.all([
    fetchJson(API_BASE),
    fetchJson(`${API_BASE}/commits/main`),
    fetchJson(`${API_BASE}/contents/package.json?ref=main`).then((data) =>
      JSON.parse(Buffer.from(data.content, "base64").toString("utf8")),
    ),
  ]);

  return {
    repo: repo.html_url,
    default_branch: repo.default_branch,
    license: repo.license?.spdx_id || null,
    pushed_at: repo.pushed_at,
    updated_at: repo.updated_at,
    latest_commit: {
      sha: commit.sha,
      date: commit.commit?.author?.date || null,
      message: commit.commit?.message || "",
      author: commit.commit?.author?.name || null,
    },
    package: {
      name: pkg.name || null,
      private: Boolean(pkg.private),
      type: pkg.type || null,
      scripts: pkg.scripts || {},
      dependencies: pkg.dependencies || {},
      devDependencies: pkg.devDependencies || {},
    },
  };
}

async function extract(args) {
  const [html, status] = await Promise.all([
    fetchText(args.source),
    upstreamStatus(),
  ]);

  const variables = parseRootVariables(html);
  const protoTemplates = parseTemplates(html);
  const cards = parseCards(html);
  const reactTemplates = parseReactTemplates(html);

  const items = cards
    .filter((card) => protoTemplates[card.key])
    .map((card) => {
      const template = protoTemplates[card.key];
      return {
        ...card,
        kind: card.key.startsWith("tok-") ? "token" : "transition",
        name: template.name || card.title,
        file: FILE_MAP[card.key] || `${card.key}.md`,
        css: buildCssSnippet(template, variables),
        react: reactTemplates[card.key] || null,
      };
    });

  return {
    source: args.source,
    extracted_at: new Date().toISOString(),
    upstream: status,
    root_css: renderRootCss(variables),
    count: items.length,
    transition_count: items.filter((item) => item.kind === "transition").length,
    token_count: items.filter((item) => item.kind === "token").length,
    items,
  };
}

function renderItemMarkdown(item, result) {
  const lines = [
    `# ${item.title}`,
    "",
    `Source: ${result.source}`,
    `Upstream commit: ${result.upstream.latest_commit.sha}`,
    `Key: \`${item.key}\``,
    `Kind: ${item.kind}`,
    "",
    item.subtitle,
    "",
    "## CSS",
    "",
    "```css",
    item.css.trimEnd(),
    "```",
    "",
  ];

  if (item.react) {
    lines.push("## React");
    lines.push("");
    lines.push("```jsx");
    lines.push(item.react.trimEnd());
    lines.push("```");
    lines.push("");
  }

  return lines.join("\n");
}

function renderMarkdown(result) {
  const lines = [
    "# Transitions.dev Extract",
    "",
    `Source: ${result.source}`,
    `Extracted: ${result.extracted_at}`,
    `Upstream commit: ${result.upstream.latest_commit.sha}`,
    `License: ${result.upstream.license || "none reported by GitHub"}`,
    `Dependencies: ${Object.keys(result.upstream.package.dependencies).length}`,
    `Dev dependencies: ${Object.keys(result.upstream.package.devDependencies).length}`,
    "",
  ];

  for (const item of result.items) {
    lines.push(`## ${item.title}`);
    lines.push("");
    lines.push(`Key: \`${item.key}\``);
    lines.push(`Kind: ${item.kind}`);
    lines.push("");
    lines.push(item.subtitle);
    lines.push("");
    lines.push("### CSS");
    lines.push("");
    lines.push("```css");
    lines.push(item.css.trimEnd());
    lines.push("```");
    lines.push("");
    if (item.react) {
      lines.push("### React");
      lines.push("");
      lines.push("```jsx");
      lines.push(item.react.trimEnd());
      lines.push("```");
      lines.push("");
    }
  }

  return lines.join("\n");
}

function resultSummary(result, files) {
  return {
    source: result.source,
    extracted_at: result.extracted_at,
    upstream: result.upstream,
    count: result.count,
    transition_count: result.transition_count,
    token_count: result.token_count,
    files,
  };
}

async function writeReferencePack(result, outDir) {
  await mkdir(outDir, { recursive: true });

  const sourceJson = {
    source: result.source,
    extracted_at: result.extracted_at,
    upstream: result.upstream,
    counts: {
      total: result.count,
      transitions: result.transition_count,
      tokens: result.token_count,
    },
    license_note:
      "GitHub reports no explicit upstream license; keep attribution and review before vendoring generated snippets into public repos.",
    files: result.items.map((item) => ({
      key: item.key,
      title: item.title,
      kind: item.kind,
      file: item.file,
    })),
  };

  const files = ["source.json", "_root.css"];
  await writeFile(
    path.join(outDir, "source.json"),
    `${JSON.stringify(sourceJson, null, 2)}\n`,
  );
  await writeFile(path.join(outDir, "_root.css"), result.root_css);

  const tokenItems = result.items.filter((item) => item.kind === "token");
  const motionTokens = [
    "# Motion Tokens",
    "",
    `Source: ${result.source}`,
    `Upstream commit: ${result.upstream.latest_commit.sha}`,
    "",
    ...tokenItems.map((item) => renderItemMarkdown(item, result)),
  ].join("\n");
  await writeFile(path.join(outDir, "motion-tokens.md"), motionTokens);
  files.push("motion-tokens.md");

  for (const item of result.items.filter((entry) => entry.kind === "transition")) {
    await writeFile(
      path.join(outDir, item.file),
      renderItemMarkdown(item, result),
    );
    files.push(item.file);
  }

  return files;
}

const args = parseArgs(process.argv.slice(2));

if (args.help) {
  console.log(usage());
  process.exit(0);
}

if (!["json", "markdown"].includes(args.format)) {
  throw new Error("--format must be json or markdown");
}

if (args.check) {
  console.log(JSON.stringify(await upstreamStatus(), null, 2));
} else {
  const result = await extract(args);
  if (args.outDir) {
    const files = await writeReferencePack(result, args.outDir);
    console.log(JSON.stringify(resultSummary(result, files), null, 2));
    process.exit(0);
  }

  if (args.format === "json") {
    console.log(JSON.stringify(result, null, 2));
  } else {
    console.log(renderMarkdown(result));
  }
}
