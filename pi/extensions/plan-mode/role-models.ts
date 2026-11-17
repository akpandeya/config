/**
 * Role → model mapping for plan mode.
 *
 * Local-only file (no upstream counterpart): plan mode switches models by phase
 * — a planner while exploring, an implementer while executing, a reviewer for
 * the deep-review pass — then restores the orchestrator that was active before
 * plan mode started.
 *
 * Edit the menus here. They are resolved against the live model registry, so a
 * model that lost its credentials (or was removed from models.json) is dropped
 * from the picker instead of breaking the switch. Prices are read from the
 * catalog at dialog time, so a router price change shows up automatically.
 *
 * The provider is hardcoded on purpose: this config is work-only (HF AI model
 * router). See pi/README.md.
 */

import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";

export type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
export type PhaseRole = "planner" | "implementer" | "reviewer";
export type Role = PhaseRole | "orchestrator";

export interface RoleModelSpec {
	provider: string;
	id: string;
	/** One-line hint shown after the price in the picker. */
	note: string;
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
	{ provider: PROVIDER, id: "GLM 5.3 Flash", note: "workhorse — fine for simple plans" },
	{ provider: PROVIDER, id: "Claude Opus 5.5", note: "hardest design / debugging" },
	{ provider: PROVIDER, id: "Heavy", note: "hardest design / debugging" },
	{ provider: PROVIDER, id: "Claude Sonnet 5.5", note: "strong general planner" },
	{ provider: PROVIDER, id: "GPT-6.1 Sol", note: "strong general planner" },
	{ provider: PROVIDER, id: "Kimi K3.1 Pro", note: "long-context planner" },
	{ provider: PROVIDER, id: "GLM 5.3", note: "mid-tier GLM" },
];

/**
 * Implementation model for an approved plan. The planner recommends one based
 * on difficulty; the picker puts that recommendation first.
 */
export const IMPLEMENTER_MODELS: readonly RoleModelSpec[] = [
	{ provider: PROVIDER, id: "GLM 5.3 Flash", note: "workhorse default" },
	{ provider: PROVIDER, id: "GPT-6 Luna", note: "cheapest — trivial tasks" },
	{ provider: PROVIDER, id: "Claude Sonnet 5.5", note: "harder changes" },
	{ provider: PROVIDER, id: "GPT-6.1 Terra", note: "harder changes" },
	{ provider: PROVIDER, id: "Kimi K3.1 Pro", note: "long-context changes" },
	{ provider: PROVIDER, id: "Heavy", note: "risky changes" },
];

/**
 * Deep-review model after the last plan step. Kimi is the default; GLM 5.3
 * Flash covers small diffs cheaply, Opus 5.5 covers risky or cross-cutting
 * changes, Sonnet 5.5 is the fallback when neither is available.
 */
export const REVIEWER_MODELS: readonly RoleModelSpec[] = [
	{ provider: PROVIDER, id: "Kimi K3.1 Pro", note: "deep review — default" },
	{ provider: PROVIDER, id: "GLM 5.3 Flash", note: "cheap second pass — small diffs" },
	{ provider: PROVIDER, id: "Claude Opus 5.5", note: "risky / cross-cutting changes" },
	{ provider: PROVIDER, id: "Claude Sonnet 5.5", note: "fallback reviewer" },
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

/**
 * Resolve the configured menu against the live registry. Falls back to a
 * provider-agnostic id/name match so a provider rename does not empty the
 * picker; anything still unresolved is dropped.
 */
export function resolveRoleModels(
	ctx: ExtensionContext,
	specs: readonly RoleModelSpec[],
): ResolvedRoleModel[] {
	const available = ctx.modelRegistry.getAvailable();
	const resolved: ResolvedRoleModel[] = [];
	const seen = new Set<string>();

	for (const spec of specs) {
		const model =
			ctx.modelRegistry.find(spec.provider, spec.id) ??
			available.find((candidate) => candidate.id === spec.id) ??
			available.find((candidate) => candidate.name.toLowerCase() === spec.id.toLowerCase());
		if (!model) continue;

		const key = modelKey(model);
		if (seen.has(key)) continue;
		seen.add(key);
		resolved.push({ model, note: spec.note });
	}

	return resolved;
}
