/**
 * Machine-agnostic compaction model overrides.
 *
 * WHY this exists: pi's `compaction.modelOverrides` keys are exact,
 * case-sensitive `provider/modelId` strings — no fuzzy matching. pi-setup
 * (@hellofresh/pi-setup) generates models.json per machine, so hand-listed
 * keys in settings.json don't port: a machine with different provider ids
 * silently misses the overrides and compacts far too early on 1M-context
 * models. This extension keeps the overrides in sync with the machine's OWN
 * catalog: on session_start it reads <agentDir>/models.json and, for every
 * provider/model with contextWindow >= 900_000, ensures
 * compaction.modelOverrides["<providerId>/<modelId>"].reserveTokens = 750_000.
 *
 * Gate: only add when contextWindow - 750_000 >= 150_000, so the resulting
 * compact-at threshold (contextWindow - reserveTokens) never drops below
 * ~150k tokens — small-window models are skipped rather than given a nonsense
 * reserve. Entries for models that left the catalog are NOT removed
 * (harmless leftovers; pi-setup may rotate ids).
 *
 * Note: keys written here only take effect from the NEXT session start —
 * pi reads settings.json at startup, so the current session keeps its
 * already-loaded compaction config.
 *
 * Concurrency: the read-modify-write below is NOT locked. Concurrent pi
 * processes syncing at startup can race and the last writer wins, dropping
 * the other process's additions until the next session start. Accepted as a
 * residual risk: entries converge once any session with a complete catalog
 * restarts, and a lost override only means an early compaction on one
 * machine until then.
 */

import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const MIN_CONTEXT_WINDOW = 900_000; // only manage 1M-class models
const RESERVE_TOKENS = 750_000;
const MIN_COMPACT_AT = 150_000; // keep compact-at >= ~150k tokens

function agentDir(): string {
	// Mirrors @hellofresh/pi-setup's agentDir(): honor the explicit override
	// first so test/staging homes work, then fall back to the default location.
	// pi expands a leading ~ in PI_CODING_AGENT_DIR, so do the same here.
	const override = process.env.PI_CODING_AGENT_DIR;
	if (override) {
		return override.startsWith("~") ? path.join(os.homedir(), override.slice(1)) : override;
	}
	return path.join(os.homedir(), ".pi", "agent");
}

function warn(message: string): void {
	process.stderr.write(`[compaction-overrides] ${message}\n`);
}

interface ModelEntry {
	id?: unknown;
	contextWindow?: unknown;
}

interface ModelsFile {
	providers?: Record<string, { models?: ModelEntry[] }>;
}

export default function compactionOverridesExtension(pi: ExtensionAPI): void {
	pi.on("session_start", async () => {
		// Belt and braces: validate container shapes AND wrap the whole sync so a
		// malformed-but-valid-JSON file can never throw out of the handler (an
		// extension crash at session_start would be worse than skipping a sync).
		try {
			await syncOverrides();
		} catch (error) {
			warn(`unexpected failure, skipping override sync: ${error instanceof Error ? error.message : String(error)}`);
		}
	});

	function isPlainObject(value: unknown): value is Record<string, unknown> {
		return typeof value === "object" && value !== null && !Array.isArray(value);
	}

	async function syncOverrides(): Promise<void> {
		const modelsFile = path.join(agentDir(), "models.json");
		let models: ModelsFile;
		try {
			models = JSON.parse(fs.readFileSync(modelsFile, "utf-8")) as ModelsFile;
		} catch (error) {
			warn(`cannot read models.json, skipping override sync: ${error instanceof Error ? error.message : String(error)}`);
			return;
		}
		if (!isPlainObject(models) || (models.providers !== undefined && !isPlainObject(models.providers))) {
			warn(`${modelsFile} has unexpected shape (expected object with optional providers object), skipping override sync`);
			return;
		}

		const settingsPath = path.join(agentDir(), "settings.json");
		let settings: Record<string, unknown>;
		try {
			const parsed: unknown = JSON.parse(fs.readFileSync(settingsPath, "utf-8"));
			if (!isPlainObject(parsed)) {
				warn(`${settingsPath} is not a JSON object, skipping override sync`);
				return;
			}
			settings = parsed;
		} catch (error) {
			warn(`cannot read settings.json, skipping override sync: ${error instanceof Error ? error.message : String(error)}`);
			return;
		}
		if (settings.compaction !== undefined && !isPlainObject(settings.compaction)) {
			warn(`${settingsPath}: "compaction" is not an object, skipping override sync`);
			return;
		}
		const compaction = (settings.compaction ??= {}) as Record<string, unknown>;
		if (compaction.modelOverrides !== undefined && !isPlainObject(compaction.modelOverrides)) {
			warn(`${settingsPath}: "compaction.modelOverrides" is not an object, skipping override sync`);
			return;
		}
		const overrides = (compaction.modelOverrides ??= {}) as Record<string, unknown>;
		let changed = false;
		for (const [providerId, provider] of Object.entries(models.providers ?? {})) {
			if (!isPlainObject(provider) || !Array.isArray(provider.models)) continue;
			for (const model of provider.models) {
				if (!isPlainObject(model)) continue;
				if (typeof model.id !== "string" || typeof model.contextWindow !== "number") continue;
				if (model.contextWindow < MIN_CONTEXT_WINDOW) continue;
				if (model.contextWindow - RESERVE_TOKENS < MIN_COMPACT_AT) continue; // compact-at would fall below ~150k
				const key = `${providerId}/${model.id}`;
				const existing = overrides[key];
				if (existing && (existing as { reserveTokens?: unknown }).reserveTokens === RESERVE_TOKENS) continue;
				overrides[key] = { ...((existing as object) ?? {}), reserveTokens: RESERVE_TOKENS };
				changed = true;
			}
		}
		if (!changed) return;

		// Unique, exclusively-created temp name: two pi processes starting at
		// once would otherwise clobber each other's staging file. The wider
		// read-modify-write race remains (documented in the header).
		const tmp = `${settingsPath}.tmp-${process.pid}-${crypto.randomUUID()}`;
		try {
			await fs.promises.writeFile(tmp, `${JSON.stringify(settings, null, 2)}\n`, {
				encoding: "utf-8",
				mode: 0o600,
				flag: "wx",
			});
			await fs.promises.rename(tmp, settingsPath);
		} catch (error) {
			warn(`could not write settings.json: ${error instanceof Error ? error.message : String(error)}`);
			await fs.promises.unlink(tmp).catch(() => {}); // best-effort cleanup
		}
	}
}
