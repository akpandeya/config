#!/usr/bin/env node
// Minimal DuckDuckGo web-search MCP server (zero-scrape-lib, plain GET).
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

const decodeEntities = (s) =>
  s
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");

const stripTags = (s) => decodeEntities(s.replace(/<[^>]*>/g, "")).replace(/\s+/g, " ").trim();

// href="//duckduckgo.com/l/?uddg=<encoded-url>&rut=..." -> real URL
function realUrl(href) {
  let u = decodeEntities(href);
  try {
    if (u.startsWith("//")) u = "https:" + u;
    const parsed = new URL(u);
    const uddg = parsed.searchParams.get("uddg");
    if (uddg) return uddg;
  } catch {
    /* fall through */
  }
  return u;
}

async function ddgSearch(query, count, safeSearch) {
  // kp: -2 strict, -1 moderate, 1 off
  const kp = safeSearch === "strict" ? "-2" : safeSearch === "off" ? "1" : "-1";
  const url = new URL("https://html.duckduckgo.com/html/");
  url.searchParams.set("q", query);
  url.searchParams.set("kp", kp);

  const res = await fetch(url, {
    headers: {
      "user-agent": UA,
      accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "accept-language": "en-US,en;q=0.9",
    },
  });
  if (!res.ok) throw new Error(`DDG returned HTTP ${res.status}`);
  const html = await res.text();
  if (html.includes("anomaly")) throw new Error("DDG anomaly page (rate limited or blocked)");

  // Link blocks: each result = <a class="result__a" href> title </a> ... <a class="result__snippet"> snippet </a>
  const linkRe = /<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
  const snippetRe = /<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)<\/a>/g;
  const titles = [];
  let m;
  while ((m = linkRe.exec(html)) && titles.length < count) titles.push({ url: realUrl(m[1]), title: stripTags(m[2]) });
  const snippets = [];
  while ((m = snippetRe.exec(html)) && snippets.length < titles.length) snippets.push(stripTags(m[1]));

  if (titles.length === 0) throw new Error("No results parsed from DDG response");
  return titles
    .map((t, i) => `${i + 1}. ${t.title}\n   ${t.url}${snippets[i] ? "\n   " + snippets[i] : ""}`)
    .join("\n");
}

const server = new Server({ name: "ddgsearch", version: "1.0.0" }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "duckduckgo_web_search",
      description:
        "Performs a web search using DuckDuckGo. Ideal for general queries, news, articles, and online content. Maximum 20 results per request.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Search query (max 400 chars)", maxLength: 400 },
          count: { type: "number", description: "Number of results (1-20, default 10)", minimum: 1, maximum: 20, default: 10 },
          safeSearch: { type: "string", description: 'SafeSearch level', enum: ["strict", "moderate", "off"], default: "moderate" },
        },
        required: ["query"],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  if (name !== "duckduckgo_web_search") {
    return { content: [{ type: "text", text: `Unknown tool: ${name}` }], isError: true };
  }
  const query = typeof args?.query === "string" ? args.query : "";
  const count = Math.min(Math.max(Number(args?.count) || 10, 1), 20);
  const safeSearch = ["strict", "moderate", "off"].includes(args?.safeSearch) ? args.safeSearch : "moderate";
  try {
    const text = await ddgSearch(query, count, safeSearch);
    return { content: [{ type: "text", text }] };
  } catch (e) {
    return { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
