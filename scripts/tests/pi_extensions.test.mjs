/**
 * Unit tests for the vendored pi extensions' enforcement wiring
 * (pi/extensions/readonly-bash.ts, subagent/agents.ts, subagent/index.ts).
 *
 * Runs under `node --test` (see scripts/tests/test_pi_extensions.py for the
 * unittest wrapper and environment setup). The TypeScript modules are loaded
 * through jiti with the same aliases pi/README.md documents for load checks.
 *
 * Env vars set by the Python wrapper:
 *   PI_EXTENSIONS_TEST_ROOT — repo root (config checkout)
 *   PI_EXTENSIONS_TEST_PKG  — @earendil-works/pi-coding-agent package root
 *
 * Sentinel mode: the subagent extension spawns child `pi` processes via
 * getPiInvocation, which reuses process.execPath + process.argv[1] — i.e. it
 * re-runs THIS file as the "pi" binary. When PI_ARGS_PROBE is set we are that
 * child: dump our argv (to PI_ARGS_PROBE_OUT when set) and exit instead of
 * running the tests.
 */
if (process.env.PI_ARGS_PROBE) {
	if (process.env.PI_ARGS_PROBE_OUT) {
		fs.writeFileSync(process.env.PI_ARGS_PROBE_OUT, JSON.stringify(process.argv.slice(2)));
	}
	process.stdout.write(JSON.stringify(process.argv.slice(2)) + "\n");
	process.exit(0);
}

import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const ROOT = process.env.PI_EXTENSIONS_TEST_ROOT;
const PKG = process.env.PI_EXTENSIONS_TEST_PKG;
if (!ROOT || !PKG) throw new Error("PI_EXTENSIONS_TEST_ROOT / PI_EXTENSIONS_TEST_PKG not set");

// jiti and the alias targets are nested under the package's own node_modules
// on npm-global installs, but hoisted to the install root when pi manages its
// own tree (e.g. ~/.pi/agent/install). Resolve whichever layout exists.
const nestedBase = path.join(PKG, "node_modules");
const hoistedBase = path.join(PKG, "..", "..");
const base = fs.existsSync(path.join(nestedBase, "jiti")) ? nestedBase : hoistedBase;
const { createJiti } = await import(path.join(base, "jiti/lib/jiti.mjs"));
const jiti = createJiti(import.meta.url, {
	alias: {
		typebox: path.join(base, "typebox/build/index.mjs"),
		"@earendil-works/pi-tui": path.join(base, "@earendil-works/pi-tui/dist/index.js"),
		"@earendil-works/pi-ai": path.join(base, "@earendil-works/pi-ai/dist/index.js"),
		"@earendil-works/pi-coding-agent": path.join(PKG, "dist/index.js"),
	},
});

function tmpDir() {
	return fs.mkdtempSync(path.join(os.tmpdir(), "pi-ext-test-"));
}

/** Load readonly-bash.ts with a stub ExtensionAPI and return the tool_call handler. */
async function loadGate(flagValue, { throwingGetFlag = false } = {}) {
	const mod = await jiti.import(path.join(ROOT, "pi/extensions/readonly-bash.ts"), { default: true });
	let handler;
	const flags = {};
	const pi = {
		registerFlag(name, options) {
			flags[name] = options;
		},
		getFlag(name) {
			if (throwingGetFlag) throw new Error("flag mechanism broken");
			return flags[name] !== undefined ? flagValue : undefined;
		},
		on(event, h) {
			if (event === "tool_call") handler = h;
		},
	};
	mod(pi);
	assert.equal(typeof handler, "function", "tool_call handler registered");
	return { handler, flags };
}

const bashCall = (command) => ({ toolName: "bash", input: { command } });

test("flag registration: boolean, default off, documented description", async () => {
	const { flags } = await loadGate(false);
	assert.deepEqual(flags["readonly-bash"], {
		description: "Restrict bash to read-only commands; blocks everything else via tool_call",
		type: "boolean",
		default: false,
	});
});

test("flag off: safe and unsafe bash both pass through unblocked", async () => {
	const { handler } = await loadGate(false);
	assert.equal(handler(bashCall("echo hi")), undefined);
	// The gate must not silently enforce when the flag is absent/false.
	assert.equal(handler(bashCall("rm -rf /tmp/whatever")), undefined);
});

test("flag on: safe command passes, unsafe command is blocked with the contract reason", async () => {
	const { handler } = await loadGate(true);
	assert.equal(handler(bashCall("git status")), undefined);
	const blocked = handler(bashCall("touch /tmp/ro-probe"));
	assert.ok(blocked?.block, "unsafe command blocked");
	// Exact contract: callers (and the dispatched model) see this full reason.
	assert.equal(blocked.reason, "Read-only bash: command not allowlisted.\nCommand: touch /tmp/ro-probe");
});

test("fail closed: getFlag throwing enforces the gate", async () => {
	const { handler } = await loadGate(undefined, { throwingGetFlag: true });
	// Fail-closed treats the flag as ENABLED: safe commands still pass, unsafe
	// ones are blocked instead of silently allowed through.
	assert.equal(handler(bashCall("git status")), undefined);
	const blocked = handler(bashCall("touch /tmp/ro-probe"));
	assert.ok(blocked?.block, "broken flag lookup must not un-restrict bash");
	assert.match(blocked.reason, /Read-only bash/);
});

test("fail closed: malformed command input is rejected, not executed", async () => {
	const { handler } = await loadGate(true);
	// null would be coerced to the string "null" by RegExp.test — it does not
	// throw, but it matches no allowlist pattern, so it must still be blocked.
	const blocked = handler({ toolName: "bash", input: { command: null } });
	assert.ok(blocked?.block, "malformed input must block, not allow");
});

test("fail closed: a command that throws during allowlist matching is blocked", async () => {
	const { handler } = await loadGate(true);
	// A poisoned coercion makes isSafeCommand's RegExp.test throw, exercising
	// the extension's catch branch — removing that catch must fail this test.
	const hostile = { [Symbol.toPrimitive]() { throw new Error("coercion boom"); } };
	const blocked = handler({ toolName: "bash", input: { command: hostile } });
	assert.ok(blocked?.block, "throwing allowlist input must block, not allow");
	assert.match(blocked.reason, /Read-only bash/);
});

test("only bash is gated: other tool calls pass through with the flag on", async () => {
	const { handler } = await loadGate(true);
	assert.equal(handler({ toolName: "edit", input: { path: "/tmp/x", oldText: "a", newText: "b" } }), undefined);
	assert.equal(handler({ toolName: "write", input: { path: "/tmp/x", content: "x" } }), undefined);
});

/**
 * Strict frontmatter parsing via the real discovery path. Project scope keeps
 * the test off the developer's real ~/.pi/agents.
 */
async function parseAgent(frontmatterBody) {
	const dir = tmpDir();
	fs.mkdirSync(path.join(dir, ".pi", "agents"), { recursive: true });
	fs.writeFileSync(
		path.join(dir, ".pi", "agents", "probe.md"),
		`---\nname: probe\ndescription: probe agent\n${frontmatterBody}\n---\n\nBody.\n`,
	);
	const { discoverAgents } = await jiti.import(path.join(ROOT, "pi/extensions/subagent/agents.ts"), {
		named: ["discoverAgents"],
	});
	const agents = discoverAgents(dir, "project").agents;
	assert.equal(agents.length, 1, "agent discovered from project dir");
	return agents[0];
}

test("frontmatter bashAllowlist: true enables the flag", async () => {
	assert.equal((await parseAgent("bashAllowlist: true")).bashAllowlist, true);
});

test("frontmatter bashAllowlist: false / absent stay off", async () => {
	assert.equal((await parseAgent("bashAllowlist: false")).bashAllowlist, false);
	assert.equal((await parseAgent("tools: read, bash")).bashAllowlist, false);
});

test("frontmatter bashAllowlist: quoted string 'true' must NOT enable (strict parse)", async () => {
	assert.equal((await parseAgent('bashAllowlist: "true"')).bashAllowlist, false);
});

/**
 * The REAL reviewer definitions must carry the flag: plan-mode's review gate
 * dispatches `reviewer` and `reviewer-strong`, and both briefs promise
 * tool-enforced bash. Synthetic fixtures cannot catch an omission here.
 */
test("real reviewer agents declare bashAllowlist: true; non-reviewer agents do not", async () => {
	const { parseFrontmatter } = await jiti.import("@earendil-works/pi-coding-agent", {
		named: ["parseFrontmatter"],
	});
	const agentsDir = path.join(ROOT, "pi/extensions/subagent/agents");
	const parsed = new Map();
	for (const entry of fs.readdirSync(agentsDir)) {
		if (!entry.endsWith(".md")) continue;
		const { frontmatter } = parseFrontmatter(fs.readFileSync(path.join(agentsDir, entry), "utf-8"));
		parsed.set(entry, frontmatter);
	}
	for (const reviewer of ["reviewer.md", "reviewer-strong.md"]) {
		assert.equal(parsed.get(reviewer)?.bashAllowlist, true, `${reviewer} must set bashAllowlist: true`);
	}
	for (const mutator of ["worker.md", "scout.md", "planner.md"]) {
		// worker.md has no tools/bashAllowlist frontmatter at all — any truthy
		// value there would be an accidental blanket edit.
		assert.ok(!parsed.get(mutator)?.bashAllowlist, `${mutator} must not set bashAllowlist`);
	}
});

/**
 * Wiring test: the dispatched child argv carries --readonly-bash exactly when
 * the agent's frontmatter sets bashAllowlist. getPiInvocation spawns
 * execPath + argv[1] + args when argv[1] exists — under `node --test` that is
 * this same file — so the "child pi" is this file re-executed, and the
 * captured argv is the real arg list the subagent extension builds. The
 * sentinel env vars are set on the test process (children inherit them) and
 * MUST NOT be set via a PATH stub: getPiInvocation never consults PATH when
 * argv[1] exists, so a PATH stub would silently never run while an unset
 * sentinel makes each child re-run the whole suite (fork bomb).
 */
async function childArgsViaStub(frontmatter) {
	const dir = tmpDir();
	const out = path.join(dir, "args.json");
	fs.mkdirSync(path.join(dir, ".pi", "agents"), { recursive: true });
	fs.writeFileSync(
		path.join(dir, ".pi", "agents", "probe.md"),
		`---\nname: probe\ndescription: probe agent\ntools: read, bash\n${frontmatter}\n---\n\nBody.\n`,
	);
	// The spawned "child pi" is this file re-executed with the sentinel env.
	process.env.PI_ARGS_PROBE = "1";
	process.env.PI_ARGS_PROBE_OUT = out;
	try {
		const mod = await jiti.import(path.join(ROOT, "pi/extensions/subagent/index.ts"), { default: true });
		let tool;
		mod({ on() {}, registerTool(t) { tool = t; } });
		const ctx = { cwd: dir, model: undefined, thinkingLevel: undefined, hasUI: false, isProjectTrusted: () => true, ui: {} };
		const result = await tool.execute("probe-call", { agent: "probe", task: "probe task", agentScope: "project" }, undefined, undefined, ctx);
		assert.equal(result.details.results[0].status, "completed", `child ran: ${result.details.results[0].errorMessage ?? "ok"}`);
		return JSON.parse(fs.readFileSync(out, "utf-8"));
	} finally {
		delete process.env.PI_ARGS_PROBE;
		delete process.env.PI_ARGS_PROBE_OUT;
	}
}

test("child argv carries --readonly-bash when the agent sets bashAllowlist", async () => {
	const args = await childArgsViaStub("bashAllowlist: true");
	assert.ok(args.includes("--readonly-bash"), `args: ${JSON.stringify(args)}`);
	// Distinguishing, non-default wiring: the --tools value must survive too.
	const toolsIdx = args.indexOf("--tools");
	assert.ok(toolsIdx !== -1, "--tools passed");
	assert.equal(args[toolsIdx + 1], "read,bash");
});

test("child argv omits --readonly-bash when the agent does not set bashAllowlist", async () => {
	const args = await childArgsViaStub("");
	assert.ok(!args.includes("--readonly-bash"), `args: ${JSON.stringify(args)}`);
	assert.ok(args.includes("--tools"), "--tools still passed");
});

/* ------------------------------------------------------------------ */
/* role-models: machine-agnostic resolver                              */
/* ------------------------------------------------------------------ */

const roleModels = await jiti.import(path.join(ROOT, "pi/extensions/plan-mode/role-models.ts"), { default: false });

function makeModel(provider, id, name, { inputCost = 1, outputCost = 2, contextWindow = 200_000, reasoning = true, input = ["text"] } = {}) {
	return { provider, id, name, api: "openai-completions", cost: { input: inputCost, output: outputCost }, contextWindow, reasoning, input };
}

/** Stub the slice of ExtensionContext resolveRoleModels touches. */
function makeCtx(models, current = models[0]) {
	return {
		model: current,
		modelRegistry: {
			getAvailable: () => models,
			find: (provider, id) => models.find((m) => m.provider === provider && m.id === id),
		},
	};
}

const OFFICE = [
	makeModel("ai-model-router", "GLM 5.3 Flash", "GLM 5.3 Flash", { inputCost: 0.15, outputCost: 0.5 }),
	makeModel("ai-model-router", "Heavy", "Heavy", { inputCost: 5, outputCost: 25 }),
	makeModel("ai-model-router", "Kimi K3.1 Pro", "Kimi K3.1 Pro", { inputCost: 1, outputCost: 5, contextWindow: 256_000 }),
];

const HOME = [
	makeModel("openrouter", "z-ai/glm-5.3-flash", "Z.ai: GLM 5.3 Flash", { inputCost: 0.1, outputCost: 0.4 }),
	makeModel("openrouter", "z-ai/glm-5.3", "Z.ai: GLM 5.3", { inputCost: 0.3, outputCost: 1 }),
	makeModel("openrouter", "moonshotai/kimi-k3.1-pro", "MoonshotAI: Kimi K3.1 Pro", { inputCost: 1, outputCost: 5, contextWindow: 256_000 }),
	makeModel("openrouter", "deepseek/deepseek-v4.1-flash", "DeepSeek: DeepSeek V4.1 Flash", { inputCost: 0.05, outputCost: 0.567 }),
	makeModel("openrouter", "vendor/whopper", "Vendor: Whopper", { inputCost: 9, outputCost: 40, contextWindow: 130_000 }),
	makeModel("openrouter", "black-forest-labs/flux-3-image", "Black Forest Labs: FLUX 3 Image", { inputCost: 0.02, outputCost: 0.02, reasoning: false, input: ["image"] }),
];

function resolvedModels(ctx, specs) {
	return roleModels.resolveRoleModels(ctx, specs).map((r) => `${r.model.provider}/${r.model.id}`);
}

test("exact provider/id match is untouched (office machine)", () => {
	assert.deepEqual(resolvedModels(makeCtx(OFFICE), roleModels.REVIEWER_MODELS.slice(0, 2)), [
		"ai-model-router/Kimi K3.1 Pro",
		"ai-model-router/GLM 5.3 Flash",
	]);
});

test("vendor prefixes resolve on a foreign catalog (home machine)", () => {
	const got = resolvedModels(makeCtx(HOME), [
		{ provider: "ai-model-router", id: "GLM 5.3 Flash", note: "" },
		{ provider: "ai-model-router", id: "Kimi K3.1 Pro", note: "" },
	]);
	assert.deepEqual(got, ["openrouter/z-ai/glm-5.3-flash", "openrouter/moonshotai/kimi-k3.1-pro"]);
});

test("tier fallback ranks the local catalog; image models excluded", () => {
	const got = resolvedModels(makeCtx(HOME), [
		{ provider: "none", id: "Heavy", note: "", tier: "strong" },
		{ provider: "none", id: "GPT-6 Luna", note: "", tier: "cheap" },
	]);
	// strong = priciest reasoning model; cheap = lowest avg cost (GLM Flash $0.25 < DeepSeek $0.31)
	assert.deepEqual(got, ["openrouter/vendor/whopper", "openrouter/z-ai/glm-5.3-flash"]);
});

test("image-only models never win a tier", () => {
	const flux = makeModel("openrouter", "vendor/pricey-image", "Vendor: Pricey Image", { inputCost: 50, outputCost: 50, reasoning: false, input: ["image"] });
	const got = resolvedModels(makeCtx([flux, ...HOME]), [{ provider: "none", id: "Heavy", note: "", tier: "strong" }]);
	assert.deepEqual(got, ["openrouter/vendor/whopper"]);
});

test("tier prefers the orchestrator's provider", () => {
	// big/one is pricier (would win on cost alone) but sits on another provider;
	// affinity must still pick the openrouter model.
	const other = [makeModel("other", "big/one", "Big One", { inputCost: 20, outputCost: 80 }), ...HOME];
	const got = resolvedModels(makeCtx(other, HOME[0]), [{ provider: "none", id: "Heavy", note: "", tier: "strong" }]);
	assert.deepEqual(got, ["openrouter/vendor/whopper"]);
});

test("long tier picks the largest context window", () => {
	const got = resolvedModels(makeCtx(HOME), [{ provider: "none", id: "Vendor X", note: "", tier: "long" }]);
	assert.deepEqual(got, ["openrouter/moonshotai/kimi-k3.1-pro"]);
});

test("numeric words must match exactly: Opus 5.5 never grabs Opus 4.5", () => {
	const mixed = [makeModel("p", "claude-opus-4.5", "Claude Opus 4.5")];
	const got = resolvedModels(makeCtx(mixed), [{ provider: "q", id: "Claude Opus 5.5", note: "" }]);
	assert.deepEqual(got, []);
});

test("unmatchable spec without a tier is dropped, not fatal", () => {
	// GLM 5.3 does fuzzy-match z-ai/glm-5.3; GPT-6.1 Sol exists on no other machine.
	const got = resolvedModels(makeCtx(HOME), [
		{ provider: "none", id: "GLM 5.3", note: "" },
		{ provider: "none", id: "GPT-6.1 Sol", note: "" },
		{ provider: "ai-model-router", id: "GLM 5.3 Flash", note: "" },
	]);
	assert.deepEqual(got, ["openrouter/z-ai/glm-5.3", "openrouter/z-ai/glm-5.3-flash"]);
});

test("duplicates collapse: no model appears twice in a resolved menu", () => {
	const got = resolvedModels(makeCtx(HOME), roleModels.IMPLEMENTER_MODELS);
	assert.ok(got.includes("openrouter/z-ai/glm-5.3-flash"));
	assert.deepEqual([...new Set(got)], got);
});

test("agent files carry no machine-pinned model", () => {
	const dir = path.join(ROOT, "pi/extensions/subagent/agents");
	for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".md"))) {
		const fm = fs.readFileSync(path.join(dir, file), "utf-8").split("---")[1] ?? "";
		assert.ok(!/^model:/m.test(fm), `${file} must not pin a model (breaks other machines)`);
	}
});

/* ------------------------------------------------------------------ */
/* plan-mode: Implementer line `; review: skip` annotation              */
/* ------------------------------------------------------------------ */

const planUtils = await jiti.import(path.join(ROOT, "pi/extensions/plan-mode/utils.ts"), { default: false });

test("review: skip marker present on the Implementer line", () => {
	const pick = planUtils.extractImplementerPick(["Implementer: glm-5.3-flash — mechanical symlink fix; review: skip"]);
	assert.equal(pick?.pick, "glm-5.3-flash");
	assert.equal(pick?.reason, "mechanical symlink fix; review: skip");
	assert.equal(pick?.reviewSkip, true);
});

test("marker absent: reviewSkip is false, reason untouched", () => {
	const pick = planUtils.extractImplementerPick(["Implementer: Claude Sonnet 5.5 — cross-cutting auth changes"]);
	assert.equal(pick?.reviewSkip, false);
	assert.equal(pick?.reason, "cross-cutting auth changes");
});

// `review: skipped` and compact `review:skip` both count as a skip request.
test("review: skipped / review:skip variants are accepted", () => {
	assert.equal(planUtils.extractImplementerPick(["Implementer: GPT-6 Luna — one-liner; review: skipped"])?.reviewSkip, true);
	assert.equal(planUtils.extractImplementerPick(["Implementer: GPT-6 Luna — one-liner; review:skip"])?.reviewSkip, true);
});

test("review mentions that are not skip requests stay false", () => {
	assert.equal(planUtils.extractImplementerPick(["Implementer: glm-5.3-flash — review: skip-tuning looks risky"])?.reviewSkip, false);
	assert.equal(planUtils.extractImplementerPick(["Implementer: glm-5.3-flash — reviewed the diff earlier"])?.reviewSkip, false);
});

test("marker inside a fenced code block is ignored (show-an-example plans)", () => {
	const blocks = [
		"Plan:\n1. Step\n\n```\nImplementer: glm-5.3-flash — example; review: skip\n```\n\nImplementer: Claude Sonnet 5.5 — real pick",
	];
	const pick = planUtils.extractImplementerPick(blocks);
	assert.equal(pick?.pick, "Claude Sonnet 5.5");
	assert.equal(pick?.reviewSkip, false);
});

test("revision override: a revised plan that drops the marker clears it", () => {
	const revised = planUtils.extractImplementerPick(["Implementer: glm-5.3-flash — mechanical; review: skip", "Implementer: glm-5.3-flash — scope grew, cross-cutting"]);
	assert.equal(revised?.reviewSkip, false);
	const kept = planUtils.extractImplementerPick(["Implementer: glm-5.3-flash — mechanical", "Implementer: glm-5.3-flash — still mechanical; review: skip"]);
	assert.equal(kept?.reviewSkip, true);
});

test("last Implementer line wins when several carry the marker", () => {
	const pick = planUtils.extractImplementerPick(["Implementer: a — x; review: skip", "Implementer: b — y"]);
	assert.equal(pick?.pick, "b");
	assert.equal(pick?.reviewSkip, false);
});

/* ------------------------------------------------------------------ */
/* plan-mode: Reviewer line (reviewer pick + rounds budget)             */
/* ------------------------------------------------------------------ */

test("Reviewer line with rounds budget", () => {
	const pick = planUtils.extractReviewerPick(["Reviewer: Kimi K3.1 Pro — deep review; rounds: 3"]);
	assert.equal(pick?.pick, "Kimi K3.1 Pro");
	assert.equal(pick?.reason, "deep review");
	assert.equal(pick?.rounds, 3);
});

test("Reviewer line without a rounds clause", () => {
	const pick = planUtils.extractReviewerPick(["Reviewer: GLM 5.3 Flash — cheap pass over a small diff"]);
	assert.equal(pick?.pick, "GLM 5.3 Flash");
	assert.equal(pick?.reason, "cheap pass over a small diff");
	assert.equal(pick?.rounds, undefined);
});

test("Reviewer line without a dash keeps the whole value as the pick", () => {
	const pick = planUtils.extractReviewerPick(["Reviewer: Kimi K3.1 Pro; rounds: 2"]);
	assert.equal(pick?.pick, "Kimi K3.1 Pro");
	assert.equal(pick?.reason, "");
	assert.equal(pick?.rounds, 2);
});

test("non-numeric rounds is ignored, not parsed", () => {
	const pick = planUtils.extractReviewerPick(["Reviewer: Kimi K3.1 Pro — rounds: many"]);
	assert.equal(pick?.pick, "Kimi K3.1 Pro");
	assert.equal(pick?.rounds, undefined);
	assert.equal(pick?.reason, "rounds: many");
});

test("Reviewer line inside a fenced code block is ignored; last line wins", () => {
	const blocks = [
		"Plan:\n1. Step\n\n```\nReviewer: Kimi K3.1 Pro — example; rounds: 5\n```\n\nReviewer: Claude Opus 5.5 — real pick; rounds: 3",
	];
	const pick = planUtils.extractReviewerPick(blocks);
	assert.equal(pick?.pick, "Claude Opus 5.5");
	assert.equal(pick?.rounds, 3);
});

test("revision override: the last Reviewer line wins (handler clears when none is left)", () => {
	const revised = planUtils.extractReviewerPick(["Reviewer: Kimi K3.1 Pro — deep; rounds: 3", "Reviewer: GLM 5.3 Flash — cheap pass"]);
	assert.equal(revised?.pick, "GLM 5.3 Flash");
	assert.equal(revised?.rounds, undefined);
});

test("no Reviewer line at all returns undefined", () => {
	assert.equal(planUtils.extractReviewerPick(["Plan:\n1. Step"]), undefined);
});

// --- background-compaction cache freshness (isCacheFresh) ---

/**
 * Regression context: computedAtTokens was recorded but never read, so a
 * summary computed at ~200k tokens could be reused when the context was near
 * 1M — the cut keeps everything after it verbatim, freeing almost nothing and
 * inviting repeated compactions.
 */
const bg = await jiti.import(path.join(ROOT, "pi/extensions/background-compaction.ts"), {
	named: ["isCacheFresh", "KEEP_RECENT_TOKENS"],
});

test("stale cache: computed at 200k, compaction near 1M is invalidated", () => {
	assert.equal(bg.isCacheFresh(200_000, 1_000_000), false);
});

test("fresh cache: computed at 200k, compaction at 240k is still reused", () => {
	assert.equal(bg.isCacheFresh(200_000, 240_000), true);
});

test("freshness boundary: exactly KEEP_RECENT_TOKENS growth is fresh, one token more is stale", () => {
	assert.equal(bg.KEEP_RECENT_TOKENS, 50_000, "must match settings.json compaction.keepRecentTokens");
	assert.equal(bg.isCacheFresh(200_000, 250_000), true);
	assert.equal(bg.isCacheFresh(200_000, 250_001), false);
});

test("KEEP_RECENT_TOKENS matches the live settings.json keepRecentTokens", () => {
	// Machine-validation, not a portable unit test: on a machine without the
	// default agent dir (custom PI_CODING_AGENT_DIR, CI scratch home) there is
	// nothing to compare, so skip instead of failing.
	const settingsPath = path.join(process.env.HOME, ".pi", "agent", "settings.json");
	if (!fs.existsSync(settingsPath)) return;
	const settings = JSON.parse(fs.readFileSync(settingsPath, "utf-8"));
	assert.equal(settings.compaction.keepRecentTokens, bg.KEEP_RECENT_TOKENS);
});

test("freshness is monotone in currentTokens", () => {
	assert.ok(bg.isCacheFresh(200_000, 200_000), "unchanged context stays fresh");
	assert.ok(!bg.isCacheFresh(200_000, 900_000), "large growth is stale");
	assert.ok(bg.isCacheFresh(900_000, 900_000), "late-computed cache is fresh");
});

/* ------------------------------------------------------------------ */
/* background-compaction: handler-level tests                           */
/* ------------------------------------------------------------------ */

/**
 * The pure isCacheFresh predicate alone cannot catch the two criticals that
 * shipped: computedAtTokens being captured AFTER the async summarization
 * completed (Finding: a cut made at 200k stamped 900k), and the freshness
 * guard failing open when getContextUsage() returns null. These tests invoke
 * the REAL extension handlers against a stub ExtensionContext, driving the
 * summarization promise manually so context growth between the cut and the
 * summary arrival is simulated exactly as it happens in production.
 */

async function loadBgExtension() {
	const mod = await jiti.import(path.join(ROOT, "pi/extensions/background-compaction.ts"), { default: true });
	const handlers = {};
	mod({
		on(event, h) {
			handlers[event] = h;
		},
	});
	return handlers;
}

/**
 * Context with a cut point: e1's 250k-char text estimates to ~62.5k tokens
 * (tokensOf: ~4 chars/token), covering KEEP_MARGIN (60k) when walking
 * backwards, so firstKeptEntryId snaps to user message e1 and e0 is summarized.
 */
const BG_ENTRIES = [
	{ id: "e0", type: "message", message: { role: "user", content: [{ type: "text", text: "hi" }], timestamp: 1 } },
	{ id: "e1", type: "message", message: { role: "user", content: [{ type: "text", text: "x".repeat(250_000) }], timestamp: 2 } },
	{ id: "e2", type: "message", message: { role: "assistant", content: [{ type: "text", text: "ok" }], timestamp: 3 } },
	{ id: "e3", type: "message", message: { role: "user", content: [{ type: "text", text: "next" }], timestamp: 4 } },
];

/** Stub the slice of ExtensionContext the handlers touch. usage is mutable. */
function makeBgCtx() {
	const state = { usageTokens: 200_000, statuses: [] };
	let resolveComplete;
	const ctx = {
		state,
		get resolveComplete() {
			return resolveComplete;
		},
		model: { provider: "p", id: "m" },
		modelRegistry: {
			find: () => ({ provider: "p", id: "m" }),
			complete: () =>
				new Promise((resolve) => {
					resolveComplete = resolve;
				}),
		},
		sessionManager: {
			buildContextEntries: () => BG_ENTRIES,
			getBranch: () => BG_ENTRIES,
		},
		getContextUsage: () => ({ tokens: state.usageTokens }),
		hasUI: false,
		ui: {
			setStatus: (_key, text) => state.statuses.push(text),
			theme: { fg: (_style, text) => text },
		},
	};
	return ctx;
}

async function waitUntil(fn, ms = 2_000) {
	const start = Date.now();
	while (!(await fn())) {
		if (Date.now() - start > ms) throw new Error("waitUntil timed out");
		await new Promise((r) => setTimeout(r, 5));
	}
}

/** Start precompute via turn_end and resolve the summarization manually. */
async function precomputeWithGrowth(handlers, ctx, tokensDuringSummarization) {
	await handlers.turn_end({ outcome: "completed" }, ctx); // fires void precompute(ctx)
	assert.equal(typeof ctx.resolveComplete, "function", "summarization request is inflight");
	// The context keeps growing while the fire-and-forget summarization runs.
	ctx.state.usageTokens = tokensDuringSummarization;
	ctx.resolveComplete({ content: [{ type: "text", text: "summary text" }] });
	await waitUntil(() => ctx.state.statuses.includes("✓ pre-compaction summary ready"));
}

/** Distinguishing, non-default values: 200_000 cut vs 300_000 current vs 50_000 window. */
test("deferred summary: cut at 200k, summary arrives after context grew past 250k → cache is stale (baseline is CUT-TIME tokens)", async () => {
	const handlers = await loadBgExtension();
	const ctx = makeBgCtx();
	// Regression: computedAtTokens used to be read from ctx AFTER the request
	// completed, stamping 300_000 and making this cache wrongly reusable.
	await precomputeWithGrowth(handlers, ctx, 300_000);
	const result = await handlers.session_before_compact(
		{ reason: "manual", preparation: { tokensBefore: 300_000 } },
		ctx,
	);
	assert.equal(result, undefined, "300k - 200k > KEEP_RECENT_TOKENS: must fall through to default compaction");

	// The stale rejection must have CLEARED the cache: with the context back at
	// 200k a still-cached summary would now be fresh and reusable — returning
	// undefined here proves invalidate() ran, not just the staleness branch.
	ctx.state.usageTokens = 200_000;
	assert.equal(
		await handlers.session_before_compact({ reason: "manual", preparation: { tokensBefore: 200_000 } }, ctx),
		undefined,
		"cache must be gone after the stale rejection",
	);
});

test("deferred summary within the freshness window: cut at 200k, summary at 240k → cached summary is reused", async () => {
	const handlers = await loadBgExtension();
	const ctx = makeBgCtx();
	await precomputeWithGrowth(handlers, ctx, 240_000);
	const result = await handlers.session_before_compact(
		{ reason: "threshold", preparation: { tokensBefore: 240_000 } },
		ctx,
	);
	assert.ok(result?.compaction, "fresh cache must be reused");
	assert.equal(result.compaction.summary, "summary text");
	assert.equal(result.compaction.firstKeptEntryId, "e1", "cut is the snapped user-message boundary");
	assert.equal(result.compaction.tokensBefore, 240_000, "event's canonical tokensBefore is forwarded");
	// Cache is consumed: a second compaction must not reuse it again.
	assert.equal(
		await handlers.session_before_compact({ reason: "manual", preparation: { tokensBefore: 240_000 } }, ctx),
		undefined,
	);
});

test("session_before_compact: null context usage falls back to preparation.tokensBefore and still guards (no fail-open)", async () => {
	const handlers = await loadBgExtension();
	const ctx = makeBgCtx();
	await precomputeWithGrowth(handlers, ctx, 200_000); // summary ready while context unchanged
	// Regression: a null live reading used to skip the freshness check entirely.
	// tokensBefore says 900k → stale → default compaction + cache cleared.
	ctx.getContextUsage = () => ({ tokens: null });
	assert.equal(
		await handlers.session_before_compact({ reason: "manual", preparation: { tokensBefore: 900_000 } }, ctx),
		undefined,
		"null usage must not bypass the freshness guard",
	);
	// Same scenario with a FRESH tokensBefore: the fallback must reuse, proving
	// the fallback value (not just absence of usage) drives the decision.
	const ctx2 = makeBgCtx();
	const handlers2 = await loadBgExtension();
	await precomputeWithGrowth(handlers2, ctx2, 240_000);
	ctx2.getContextUsage = () => undefined;
	const result = await handlers2.session_before_compact(
		{ reason: "manual", preparation: { tokensBefore: 240_000 } },
		ctx2,
	);
	assert.ok(result?.compaction, "fresh tokensBefore fallback must reuse the cache");
});

test("session_before_compact: overflow recovery never reuses the cache, even a fresh one", async () => {
	const handlers = await loadBgExtension();
	const ctx = makeBgCtx();
	await precomputeWithGrowth(handlers, ctx, 200_000);
	assert.equal(
		await handlers.session_before_compact({ reason: "overflow", preparation: { tokensBefore: 200_000 } }, ctx),
		undefined,
	);
	// Invalidated: with usage back in the fresh window nothing is returned.
	assert.equal(
		await handlers.session_before_compact({ reason: "manual", preparation: { tokensBefore: 200_000 } }, ctx),
		undefined,
	);
});

// ---------------------------------------------------------------------------
// steering-frame.ts — steering delivery framing state machine
// ---------------------------------------------------------------------------

async function loadSteeringFrame() {
	const mod = await jiti.import(path.join(ROOT, "pi/extensions/steering-frame.ts"), { default: true });
	const handlers = {};
	const status = {};
	const pi = {
		on(event, handler) {
			(handlers[event] ??= []).push(handler);
		},
		ui: {
			setStatus(key, value) {
				status[key] = value;
			},
			theme: { fg: (_kind, text) => text },
		},
	};
	await mod(pi);
	const ctx = { ui: pi.ui };
	const fire = async (event, payload) => {
		const results = [];
		for (const handler of handlers[event] ?? []) results.push(await handler(payload, ctx));
		return results;
	};
	return { fire, status };
}

let steerSeq = 0;
const userMsg = (content) => ({ role: "user", content, timestamp: ++steerSeq });
const imageOnlyMsg = () => ({
	role: "user",
	content: [{ type: "image", data: "abc", mimeType: "image/png" }],
	timestamp: ++steerSeq,
});
const toolResultMsg = (text) => ({ role: "toolResult", content: [{ type: "text", text }], timestamp: ++steerSeq });
const assistantToolMsg = () => ({
	role: "assistant",
	content: [{ type: "toolCall", id: "t1", name: "bash", arguments: {} }],
	timestamp: ++steerSeq,
});

/** Simulate the run reaching its first assistant message (enables delivery correlation). */
async function runStarted(ext) {
	await ext.fire("agent_start", {});
	await ext.fire("message_end", { message: assistantToolMsg() });
}

/**
 * Simulate the native drain: each text is appended as a user message
 * (message_end fires per message), then the next LLM call prepares. Inputs
 * must be recorded beforehand via fire("input", ...) — one per typed message.
 */
async function deliverAndPrepare(ext, transcript, texts) {
	for (const text of texts) {
		transcript.push(userMsg(text));
		await ext.fire("message_end", { message: transcript[transcript.length - 1] });
	}
	const results = await ext.fire("context_with_system", { messages: transcript });
	return results[0];
}

test("steering-frame: single steer is framed at the next boundary and cleared after the turn", async () => {
	const ext = await loadSteeringFrame();
	await runStarted(ext);
	await ext.fire("input", { text: "Also run echo DELTA", streamingBehavior: "steer" });
	const transcript = [userMsg("task"), assistantToolMsg(), toolResultMsg("ok")];
	const result = (await deliverAndPrepare(ext, transcript, ["Also run echo DELTA"]))?.messages;
	const last = result[result.length - 1];
	assert.equal(last.role, "user");
	assert.match(last.content, /<user-steering>/);
	assert.match(last.content, /1\. Also run echo DELTA/);
	assert.equal(result.length, transcript.length, "batch folds into one message");
	// Framed records stay until the turn completes (retry safety)...
	const retry = (await ext.fire("context_with_system", { messages: transcript }))[0]?.messages;
	assert.match(retry[retry.length - 1].content, /<user-steering>/, "retry re-frames");
	// ...and are dropped once the turn completes, so the next idle prompt is raw.
	await ext.fire("turn_end", { outcome: "completed" });
	const idle = [userMsg("new prompt")];
	const idleResult = (await ext.fire("context_with_system", { messages: idle }))[0];
	assert.equal(idleResult, undefined, "idle prompt is not framed");
});

test("steering-frame: batch of two steers frames as one numbered block", async () => {
	const ext = await loadSteeringFrame();
	await runStarted(ext);
	await ext.fire("input", { text: "Also run echo FIVE", streamingBehavior: "steer" });
	await ext.fire("input", { text: "Include MANGO in the report", streamingBehavior: "steer" });
	const transcript = [userMsg("task"), assistantToolMsg(), toolResultMsg("ok")];
	const result = (await deliverAndPrepare(ext, transcript, ["Also run echo FIVE", "Include MANGO in the report"]))?.messages;
	const last = result[result.length - 1];
	assert.match(last.content, /2 messages arrived/);
	assert.match(last.content, /1\. Also run echo FIVE/);
	assert.match(last.content, /2\. Include MANGO in the report/);
});
test("steering-frame: a steer queued during preparation does not block the delivered batch", async () => {
	const ext = await loadSteeringFrame();
	await runStarted(ext);
	const transcript = [userMsg("task"), assistantToolMsg(), toolResultMsg("ok")];
	// A and B are queued and delivered; C is queued after B's delivery (while
	// the request is being prepared) but before the context hook runs.
	await ext.fire("input", { text: "steer A", streamingBehavior: "steer" });
	await ext.fire("input", { text: "steer B", streamingBehavior: "steer" });
	transcript.push(userMsg("steer A"));
	await ext.fire("message_end", { message: transcript[transcript.length - 1] });
	transcript.push(userMsg("steer B"));
	await ext.fire("message_end", { message: transcript[transcript.length - 1] });
	await ext.fire("input", { text: "steer C", streamingBehavior: "steer" });
	const result = (await ext.fire("context_with_system", { messages: transcript }))[0]?.messages;
	assert.match(result[result.length - 1].content, /steer A/);
	assert.match(result[result.length - 1].content, /steer B/);
	assert.doesNotMatch(result[result.length - 1].content, /steer C/, "newer queued steer stays pending");
	await ext.fire("turn_end", { outcome: "completed" });
	// Next boundary delivers C alone.
	const transcript2 = [...transcript, assistantToolMsg(), toolResultMsg("ok2")];
	const result2 = (await deliverAndPrepare(ext, transcript2, ["steer C"]))?.messages;
	assert.match(result2[result2.length - 1].content, /1\. steer C/);
});

test("steering-frame: expanded steer retires at delivery and cannot frame a later follow-up", async () => {
	const ext = await loadSteeringFrame();
	await runStarted(ext);
	await ext.fire("input", { text: "/review", streamingBehavior: "steer" });
	const transcript = [userMsg("task"), assistantToolMsg(), toolResultMsg("ok")];
	// Delivery: the expanded text shares no prefix with the raw "/review".
	const result = await deliverAndPrepare(ext, transcript, ["Review the whole diff carefully and report findings"]);
	const delivered = (result?.messages ?? transcript)[transcript.length - 1];
	assert.doesNotMatch(typeof delivered.content === "string" ? delivered.content : "", /user-steering/, "expanded steer delivers unframed");
	await ext.fire("turn_end", { outcome: "completed" });
	// A later follow-up starting with the raw command must NOT be framed.
	const transcript2 = [...transcript, assistantToolMsg(), toolResultMsg("ok2")];
	const result2 = await deliverAndPrepare(ext, transcript2, ["/review-notes for the team"]);
	const delivered2 = (result2?.messages ?? transcript2)[transcript2.length - 1];
	assert.doesNotMatch(typeof delivered2.content === "string" ? delivered2.content : "", /user-steering/, "no false frame from retired record");
});

test("steering-frame: image-only steer is framed with a placeholder and preserved blocks", async () => {
	const ext = await loadSteeringFrame();
	await runStarted(ext);
	await ext.fire("input", { text: "", images: [{ type: "image", data: "abc", mimeType: "image/png" }], streamingBehavior: "steer" });
	const transcript = [userMsg("task"), assistantToolMsg(), toolResultMsg("ok"), imageOnlyMsg()];
	await ext.fire("message_end", { message: transcript[transcript.length - 1] });
	const result = (await ext.fire("context_with_system", { messages: transcript }))[0]?.messages;
	const last = result[result.length - 1];
	assert.equal(last.role, "user");
	assert.match(last.content[0].text, /\(image attachment, no text\)/);
	assert.equal(last.content.length, 2, "image block preserved after the frame text");
	assert.equal(last.content[1].type, "image");
	await ext.fire("turn_end", { outcome: "completed" });
});

test("steering-frame: steer consumed as a run prompt is dropped by the race guard", async () => {
	const ext = await loadSteeringFrame();
	await runStarted(ext);
	await ext.fire("input", { text: "run the checks", streamingBehavior: "steer" });
	// The steer became the next run's starting prompt instead of queuing.
	await ext.fire("before_agent_start", { messageType: "user", prompt: "run the checks" });
	const idle = [userMsg("run the checks"), assistantToolMsg(), toolResultMsg("ok")];
	const result = (await ext.fire("context_with_system", { messages: idle }))[0];
	assert.equal(result, undefined, "race-consumed steer is not framed");
	// And the run prompt itself is untouched even before the turn completes.
	const withBatch = [userMsg("run the checks"), assistantToolMsg(), toolResultMsg("ok"), userMsg("genuine steer")];
	await ext.fire("input", { text: "genuine steer", streamingBehavior: "steer" });
	await ext.fire("message_end", { message: withBatch[withBatch.length - 1] });
	const result2 = (await ext.fire("context_with_system", { messages: withBatch }))[0]?.messages;
	assert.match(result2[result2.length - 1].content, /1\. genuine steer/);
});

test("steering-frame: settle clears pending state so an unrelated prompt is never framed", async () => {
	const ext = await loadSteeringFrame();
	await runStarted(ext);
	await ext.fire("input", { text: "steer X", streamingBehavior: "steer" });
	// Abort: pi returns queued messages to the editor; settle fires.
	await ext.fire("agent_settled", { aborted: true });
	assert.equal(ext.status["steer-frame"], undefined, "status cleared on settle");
	const idle = [userMsg("fresh prompt")];
	const result = (await ext.fire("context_with_system", { messages: idle }))[0];
	assert.equal(result, undefined);
});

test("steering-frame: multi-line steers keep one number with indented continuation", async () => {
	const ext = await loadSteeringFrame();
	await runStarted(ext);
	await ext.fire("input", { text: "first line\nsecond line", streamingBehavior: "steer" });
	const transcript = [userMsg("task"), assistantToolMsg(), toolResultMsg("ok")];
	const result = (await deliverAndPrepare(ext, transcript, ["first line\nsecond line"]))?.messages;
	const last = result[result.length - 1];
	assert.match(last.content, /1\. first line\n   second line/);
});

test("steering-frame: whitespace-only input without images is not recorded", async () => {
	const ext = await loadSteeringFrame();
	await runStarted(ext);
	await ext.fire("input", { text: "   ", streamingBehavior: "steer" });
	const idle = [userMsg("prompt"), assistantToolMsg(), toolResultMsg("ok")];
	const result = (await ext.fire("context_with_system", { messages: idle }))[0];
	assert.equal(result, undefined);
});
