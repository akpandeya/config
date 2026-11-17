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

const { createJiti } = await import(path.join(PKG, "node_modules/jiti/lib/jiti.mjs"));
const base = path.join(PKG, "node_modules");
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
