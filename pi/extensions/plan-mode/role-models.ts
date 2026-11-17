/**
 * Role → model mapping for plan mode.
 *
 * Local-only file (no upstream counterpart): plan mode switches models by phase
 * — a planner while exploring, an implementer while executing, a reviewer for
 * the deep-review pass — then restores the orchestrator that was active before
 * plan mode started.
 *
 * Machine-agnostic resolution. The menus below are written against the HF AI
 * model router (the work machine), but `resolveRoleModels` degrades cleanly on
 * any other setup instead of silently emptying the pickers:
 *
 * 1. Exact match: `find(provider, id)`, then id, then name (ci) — the office
 *    machine resolves everything here, unchanged.
 * 2. Vendor-prefix fuzzy match: openrouter-style catalogs prefix names
 *    ("MoonshotAI: Kimi K3.1 Pro") and paths ("z-ai/glm-5.3-flash"); both are
 *    stripped before comparison, plus a word-token match for near misses.
 * 3. Capability tiers: names that exist on no other machine ("Heavy",
 *    "GPT-6 Luna") fall back to ranking the local catalog by cost/context —
 *    the spec's `tier` says what role the model plays, not what it is called.
 * 4. Provider affinity: fuzzy/tier matches prefer the orchestrator's current
 *    provider, so the resolved model has credentials on this machine.
 *
 * Edit the menus here. They are resolved against the live model registry, so a
 * model that lost its credentials is dropped from the picker instead of
 * breaking the switch. Prices are read from the catalog at dialog time.
 */

import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

export type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
export type PhaseRole = "planner" | "implementer" | "reviewer";
export type Role = PhaseRole | "orchestrator";

/**
 * What a spec's model is *for*, used to rank the local catalog when the name
 * cannot be matched on this machine.
 */
export type ModelTier = "cheap" | "strong" | "long";

export interface RoleModelSpec {
	provider: string;
	id: string;
	/** One-line hint shown after the price in the picker. */
	note: string;
	/** Fallback ranking when the name does not exist on this machine. */
	tier?: ModelTier;
}

export interface ResolvedRoleModel {
	model: Model<Api>;
	note: string;
}

const PROVIDER = "ai-model-router";

/**
 * Planning model for the first plan turn. GLM 5.3 Flash is first on purpose:
 * it plans simple work well, and Enter on the picker keeps it. Stronger models
 * are listed for complex design work.
 */
export const PLANNER_MODELS: readonly RoleModelSpec[] = [
	{ provider: PROVIDER, id: "GLM 5.3 Flash", note: "workhorse — fine for simple plans", tier: "cheap" },
	{ provider: PROVIDER, id: "Claude Opus 5.5", note: "hardest design / debugging", tier: "strong" },
	{ provider: PROVIDER, id: "Heavy", note: "hardest design / debugging", tier: "strong" },
	{ provider: PROVIDER, id: "Claude Sonnet 5.5", note: "strong general planner", tier: "strong" },
	{ provider: PROVIDER, id: "GPT-6.1 Sol", note: "strong general planner", tier: "strong" },
	{ provider: PROVIDER, id: "Kimi K3.1 Pro", note: "long-context planner", tier: "long" },
	{ provider: PROVIDER, id: "GLM 5.3", note: "mid-tier GLM" },
];

/**
 * Implementation model for an approved plan. The planner recommends one based
 * on difficulty; the picker puts that recommendation first.
 */
export const IMPLEMENTER_MODELS: readonly RoleModelSpec[] = [
	{ provider: PROVIDER, id: "GLM 5.3 Flash", note: "workhorse default", tier: "cheap" },
	{ provider: PROVIDER, id: "GPT-6 Luna", note: "cheapest — trivial tasks", tier: "cheap" },
	{ provider: PROVIDER, id: "Claude Sonnet 5.5", note: "harder changes", tier: "strong" },
	{ provider: PROVIDER, id: "GPT-6.1 Terra", note: "harder changes", tier: "strong" },
	{ provider: PROVIDER, id: "Kimi K3.1 Pro", note: "long-context changes", tier: "long" },
	{ provider: PROVIDER, id: "Heavy", note: "risky changes", tier: "strong" },
];

/**
 * Deep-review model after the last plan step. Kimi is the default; GLM 5.3
 * Flash covers small diffs cheaply, Opus 5.5 covers risky or cross-cutting
 * changes, Sonnet 5.5 is the fallback when neither is available.
 */
export const REVIEWER_MODELS: readonly RoleModelSpec[] = [
	{ provider: PROVIDER, id: "Kimi K3.1 Pro", note: "deep review — default", tier: "long" },
	{ provider: PROVIDER, id: "GLM 5.3 Flash", note: "cheap second pass — small diffs", tier: "cheap" },
	{ provider: PROVIDER, id: "Claude Opus 5.5", note: "risky / cross-cutting changes", tier: "strong" },
	{ provider: PROVIDER, id: "Claude Sonnet 5.5", note: "fallback reviewer", tier: "strong" },
];

/** Thinking level to apply with each phase switch (clamped to the model). */
export const ROLE_THINKING: Record<Role, ThinkingLevel> = {
	planner: "high",
	implementer: "medium",
	reviewer: "high",
	orchestrator: "low",
};

export function modelKey(model: Pick<Model<Api>, "provider" | "id">): string {
	return `${model.provider}/${model.id}`;
}

function usd(value: number): string {
	return `$${value.toFixed(2)}`.replace(/\.00$/, "");
}

/** `$in/$out per 1M` from the catalog, e.g. `$0.15/$0.50 per 1M`. */
export function formatModelCost(model: Model<Api>): string {
	return `${usd(model.cost.input)}/${usd(model.cost.output)} per 1M`;
}

/** Picker line: name, price, and the role hint. */
export function describeRoleModel(candidate: ResolvedRoleModel): string {
	return `${candidate.model.name} — ${formatModelCost(candidate.model)} — ${candidate.note}`;
}

/* ------------------------------------------------------------------ */
/* Matching                                                            */
/* ------------------------------------------------------------------ */

/** Lowercase word tokens, e.g. "Claude Opus 5.5" → ["claude","opus","5.5"]. Decimal version words stay whole, so 5.5 never matches 4.5. */
function words(s: string): string[] {
	return s
		.toLowerCase()
		.split(/[^a-z0-9.]+/)
		.filter(Boolean);
}

/** Drop a catalog's vendor prefixes: "z-ai/glm-5.3-flash" → "glm-5.3-flash", "MoonshotAI: Kimi K3.1 Pro" → "Kimi K3.1 Pro". */
function bareModelName(display: string): string {
	const noPath = display.includes("/") ? display.slice(display.lastIndexOf("/") + 1) : display;
	const colon = noPath.indexOf(":");
	return (colon > 0 ? noPath.slice(colon + 1) : noPath).trim();
}

/** Compare two model names ignoring separators/prefixes, e.g. "GLM 5.3 Flash" ≡ "z-ai/glm-5.3-flash". */
function namesEquivalent(a: string, b: string): boolean {
	const squash = (s: string) => bareModelName(s).toLowerCase().replace(/[^a-z0-9]/g, "");
	return squash(a) === squash(b) && squash(a) !== "";
}

/**
 * Word-token match: every non-numeric spec word must appear in the candidate's
 * id/name words; numeric words must match exactly (so "Opus 5.5" never grabs
 * "Opus 4.5"). Score = numeric hits, for ordering near misses.
 */
function tokenMatchScore(specWords: string[], candidateWords: string[]): number | undefined {
	const numeric = (w: string) => /^\d/.test(w);
	const specNumeric = specWords.filter(numeric);
	const specWordsNon = specWords.filter((w) => !numeric(w));
	if (!specWordsNon.every((w) => candidateWords.includes(w))) return undefined;
	const numericHits = specNumeric.filter((w) => candidateWords.includes(w)).length;
	if (specNumeric.length > 0 && numericHits === 0) return undefined;
	return numericHits;
}

/**
 * Rank the local catalog for a tier. Text-capable models only (no image
 * generators); cheap/strong need a usable context window; strong also wants a
 * reasoning model, since price alone is the capability proxy here.
 */
export function pickTierModel(
	available: readonly Model<Api>[],
	tier: ModelTier,
	preferredProvider?: string,
): Model<Api> | undefined {
	const textModels = available.filter((m) => {
		const inputs = (m as { input?: readonly string[] }).input;
		return inputs === undefined || inputs.includes("text");
	});
	const usable = textModels.filter((m) => {
		const ctxWindow = (m as { contextWindow?: number }).contextWindow;
		return ctxWindow === undefined || ctxWindow >= 128_000;
	});
	const pool = (tier === "long" ? textModels : usable).filter(
		(m) => Number.isFinite(m.cost?.input) && Number.isFinite(m.cost?.output),
	);
	if (pool.length === 0) return undefined;

	const avgCost = (m: Model<Api>) => (m.cost.input + m.cost.output) / 2;
	const ctxWindow = (m: Model<Api>) => (m as { contextWindow?: number }).contextWindow ?? 0;
	const isReasoning = (m: Model<Api>) => Boolean((m as { reasoning?: boolean }).reasoning);
	const sameProvider = (m: Model<Api>) => (preferredProvider && m.provider === preferredProvider ? 0 : 1);

	const ranked = [...pool].sort((a, b) => {
		const byProvider = sameProvider(a) - sameProvider(b);
		if (byProvider !== 0) return byProvider;
		if (tier === "cheap") return avgCost(a) - avgCost(b);
		if (tier === "strong") return avgCost(b) - avgCost(a);
		return ctxWindow(b) - ctxWindow(a);
	});
	if (tier === "strong" && ranked[0] && !isReasoning(ranked[0])) {
		// Price alone is the capability proxy; a non-reasoning model that merely
		// prices high is not what "hardest" means. Swap for the priciest
		// reasoning model with the same provider affinity instead.
		const topAffinity = sameProvider(ranked[0]);
		const reasoningFirst = ranked.find((m) => sameProvider(m) === topAffinity && isReasoning(m));
		if (reasoningFirst) return reasoningFirst;
	}
	return ranked[0];
}

/* ------------------------------------------------------------------ */
/* Resolution                                                          */
/* ------------------------------------------------------------------ */

/**
 * Resolve the configured menu against the live registry:
 * exact → fuzzy (vendor prefixes / tokens) → tier ranking. Fuzzy and tier
 * matches prefer the orchestrator's provider so the result has credentials.
 * Anything still unresolved is dropped.
 */
export function resolveRoleModels(
	ctx: ExtensionContext,
	specs: readonly RoleModelSpec[],
): ResolvedRoleModel[] {
	const available = ctx.modelRegistry.getAvailable();
	const preferred = ctx.model?.provider;
	const resolved: ResolvedRoleModel[] = [];
	const seen = new Set<string>();

	for (const spec of specs) {
		const specWords = words(spec.id);
		const model =
			// 1. Exact: provider/id, then id anywhere, then display name (ci).
			ctx.modelRegistry.find(spec.provider, spec.id) ??
			available.find((c) => c.id === spec.id) ??
			available.find((c) => c.name.toLowerCase() === spec.id.toLowerCase()) ??
			// 2. Fuzzy: vendor prefixes ("MoonshotAI: X", "z-ai/x") and token near misses.
			available.find((c) => namesEquivalent(spec.id, c.name) || namesEquivalent(spec.id, c.id)) ??
			available
				.map((c) => ({
					c,
					score: tokenMatchScore(specWords, words(c.id)) ?? tokenMatchScore(specWords, words(c.name)),
				}))
				.filter((m): m is { c: Model<Api>; score: number } => m.score !== undefined)
				.sort((a, b) =>
					(b.score - a.score) ||
					((a.c.provider === preferred ? 0 : 1) - (b.c.provider === preferred ? 0 : 1)),
				)
				.map((m) => m.c)[0] ??
			// 3. Tier fallback: rank the local catalog by what the role needs.
			(spec.tier ? pickTierModel(available, spec.tier, preferred) : undefined);
		if (!model) continue;

		const key = modelKey(model);
		if (seen.has(key)) continue;
		seen.add(key);
		resolved.push({ model, note: spec.note });
	}

	return resolved;
}
