/**
 * Plan Mode Extension — vendored copy
 *
 * Upstream: examples/extensions/plan-mode/ in @earendil-works/pi-coding-agent
 * (https://github.com/earendil-works/pi), copied from pi 1.5.2.
 * Linked to ~/.pi/agent/extensions/plan-mode by setup-dev-env.sh so every
 * machine runs the same version. Update steps: pi/README.md.
 *
 * Read-only exploration mode for safe code analysis.
 * When enabled, built-in write tools are disabled.
 *
 * Features:
 * - /plan command or Ctrl+Alt+P to toggle
 * - Shift+Tab: plan -> approval dialog -> execute, asked again until approved
 * - Bash restricted to allowlisted read-only commands
 * - Extracts numbered plan steps from "Plan:" sections
 * - [DONE:n] markers to complete steps during execution
 * - Progress widget above the editor during execution: numbered steps, laid out
 *   in 1-4 columns to use the terminal width, capped at MAX_WIDGET_ROWS rows
 *   with the remainder behind /todos (see todos-view.ts)
 * - /todos opens the full list in a scrollable overlay
 * - Role-based models: planner picker on the first plan turn, implementer picker
 *   on approval, deep-review pass after the last step, then the orchestrator
 *   model is restored (see role-models.ts)
 */

import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { Api, AssistantMessage, Model, TextContent } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { Key } from "@earendil-works/pi-tui";
import { OVERLAY_PAGE_ROWS, createTodoOverlay, renderTodoWidget } from "./todos-view.ts";
import {
	IMPLEMENTER_MODELS,
	PLANNER_MODELS,
	REVIEWER_MODELS,
	ROLE_THINKING,
	describeRoleModel,
	formatModelCost,
	modelKey,
	resolveRoleModels,
	type PhaseRole,
	type ThinkingLevel,
} from "./role-models.ts";
import {
	allStepsComplete,
	extractImplementerPick,
	extractReviewVerdict,
	extractTodoItemsFromBlocks,
	isSafeCommand,
	markCompletedSteps,
	matchModelChoice,
	type ImplementerPick,
	type TodoItem,
} from "./utils.ts";

// Tools
const PLAN_MODE_TOOLS = ["read", "bash", "grep", "find", "ls", "questionnaire"];
const NORMAL_MODE_TOOLS = ["read", "bash", "edit", "write", "plan_done"];
// plan_done is excluded in plan mode so the model can't tick steps early; it is
// only active during execution, where it marks steps done immediately.
const PLAN_MODE_DISABLED_TOOLS = new Set<string>(["edit", "write", "plan_done"]);
const PLAN_MANAGED_TOOLS = new Set<string>([...PLAN_MODE_TOOLS, ...NORMAL_MODE_TOOLS]);
// Review is read-only. Do not inherit custom tools: they may mutate state.
const REVIEW_MODE_TOOLS = ["read", "bash", "grep", "find", "ls"];
// Agents the parent may dispatch while a read-only guarantee is active. The
// `worker` agent mutates files, so it is excluded: dispatching it from plan or
// review mode would bypass the tool restrictions through the subagent.
const READONLY_AGENTS = new Set(["scout", "reviewer", "reviewer-strong"]);

interface SavedModel {
	provider: string;
	id: string;
	thinkingLevel: ThinkingLevel;
}

interface PlanModeState {
	enabled: boolean;
	todos?: TodoItem[];
	executing?: boolean;
	awaitingAnswers?: boolean;
	toolsBeforePlanMode?: string[];
	plannerChosen?: boolean;
	planner?: SavedModel;
	orchestrator?: SavedModel;
	implementer?: SavedModel;
	implementerIsolated?: boolean;
	reviewer?: SavedModel;
	reviewing?: boolean;
	reviewRound?: number;
	toolsBeforeReview?: string[];
	mutated?: boolean;
}

/** Review rounds before the extension stops asking for fixes and reports instead. */
const MAX_REVIEW_ROUNDS = 2;

// Type guard for assistant messages
function isAssistantMessage(m: AgentMessage): m is AssistantMessage {
	return m.role === "assistant" && Array.isArray(m.content);
}

// Extract text content from an assistant message.
// Includes thinking blocks: with reasoning-max models the [DONE:n] tags and
// plan drafts usually land in thinking, not the visible text.
function getTextContent(message: AssistantMessage): string {
	return message.content
		.map((block) => {
			if (block.type === "text") return block.text;
			if (block.type === "thinking") return (block as { thinking?: string }).thinking ?? "";
			return "";
		})
		.join("\n");
}

// Per-content-block view of an assistant message, for plan extraction: thinking
// and text are kept separate so a draft plan in thinking can't merge with the
// final plan in the text block (see extractTodoItemsFromBlocks).
function getContentBlocks(message: AssistantMessage): string[] {
	return message.content.map((block) => {
		if (block.type === "text") return block.text;
		if (block.type === "thinking") return (block as { thinking?: string }).thinking ?? "";
		return "";
	});
}

export default function planModeExtension(pi: ExtensionAPI): void {
	let planModeEnabled = false;
	let executionMode = false;
	let awaitingAnswers = false;
	let todoItems: TodoItem[] = [];
	let toolsBeforePlanMode: string[] | undefined;
	// Role switching state. `orchestrator` is captured before the first switch and
	// restored when the plan finishes or plan mode is left.
	let plannerChosen = false;
	let plannerModel: SavedModel | undefined;
	let orchestrator: SavedModel | undefined;
	let implementerModel: SavedModel | undefined;
	// When true, execution is delegated to per-step `worker` subagents instead of
	// running inline in this session.
	let implementerIsolated = false;
	let reviewerModel: SavedModel | undefined;
	let reviewing = false;
	let reviewRound = 0;
	let toolsBeforeReview: string[] | undefined;
	// Set by tool results during execution: a plan that never mutated anything
	// skips the review pass.
	let mutatedThisExecution = false;
	let lastImplementerPick: ImplementerPick | undefined;

	pi.registerFlag("plan", {
		description: "Start in plan mode (read-only exploration)",
		type: "boolean",
		default: false,
	});

	function updateStatus(ctx: ExtensionContext): void {
		const model = ctx.model ? ` · ${ctx.model.name}` : "";

		// Footer status
		if (executionMode && todoItems.length > 0) {
			const completed = todoItems.filter((t) => t.completed).length;
			const label = reviewing ? "🔍 review" : `📋 ${completed}/${todoItems.length}`;
			ctx.ui.setStatus("plan-mode", ctx.ui.theme.fg("accent", `${label}${model}`));
		} else if (planModeEnabled) {
			ctx.ui.setStatus(
				"plan-mode",
				ctx.ui.theme.fg(
					awaitingAnswers ? "accent" : "warning",
					`${awaitingAnswers ? "⏳ awaiting answers" : "⏸ plan"}${model}`,
				),
			);
		} else {
			ctx.ui.setStatus("plan-mode", undefined);
		}

		// Widget above the editor. Columns adapt to the terminal width, so the
		// layout has to be computed per render width rather than up front.
		if (executionMode && todoItems.length > 0) {
			const snapshot = todoItems.map((item) => `${item.step}:${item.completed ? 1 : 0}`).join(",");
			ctx.ui.setWidget("plan-todos", (_tui, theme) => {
				let cachedWidth: number | undefined;
				let cachedSnapshot = "";
				let cachedLines: string[] | undefined;
				return {
					render(width: number): string[] {
						if (cachedLines && cachedWidth === width && cachedSnapshot === snapshot) return cachedLines;
						cachedWidth = width;
						cachedSnapshot = snapshot;
						cachedLines = renderTodoWidget(todoItems, width, theme);
						return cachedLines;
					},
					invalidate(): void {
						cachedLines = undefined;
					},
				};
			});
		} else {
			ctx.ui.setWidget("plan-todos", undefined);
		}
	}

	function uniqueToolNames(toolNames: string[]): string[] {
		return [...new Set(toolNames)];
	}

	/** True when the subagent extension is loaded and its tool is active. */
	function subagentToolActive(): boolean {
		return pi.getActiveTools().includes("subagent");
	}

	function getPlanModeTools(activeToolNames: string[]): string[] {
		return uniqueToolNames([
			...activeToolNames.filter((name) => !PLAN_MODE_DISABLED_TOOLS.has(name)),
			...PLAN_MODE_TOOLS,
		]);
	}

	function getNormalModeTools(activeToolNames: string[]): string[] {
		return uniqueToolNames([
			...NORMAL_MODE_TOOLS,
			...activeToolNames.filter((name) => !PLAN_MANAGED_TOOLS.has(name)),
		]);
	}

	function enablePlanModeTools(): void {
		if (toolsBeforePlanMode === undefined) {
			toolsBeforePlanMode = pi.getActiveTools();
		}
		pi.setActiveTools(getPlanModeTools(toolsBeforePlanMode));
	}

	function restoreNormalModeTools(): void {
		pi.setActiveTools(toolsBeforePlanMode ?? getNormalModeTools(pi.getActiveTools()));
		toolsBeforePlanMode = undefined;
	}

	/**
	 * Option labels are the picker's return values (`options.indexOf(choice)`),
	 * so duplicates would select the first match. Disambiguate on collision.
	 */
	function uniqueLabels(
		labels: readonly string[],
		candidates: ReturnType<typeof resolveRoleModels>,
	): string[] {
		const seen = new Map<string, number>();
		return labels.map((label, index) => {
			const count = seen.get(label) ?? 0;
			seen.set(label, count + 1);
			if (count === 0) return label;
			const model = candidates[index]?.model;
			return model ? `${label} (${model.provider}/${model.id})` : `${label} (${index + 1})`;
		});
	}

	function snapshotModel(ctx: ExtensionContext): SavedModel | undefined {
		const model = ctx.model;
		if (!model) return undefined;
		return { provider: model.provider, id: model.id, thinkingLevel: pi.getThinkingLevel() };
	}

	function isCurrentModel(ctx: ExtensionContext, model: { provider: string; id: string }): boolean {
		return ctx.model?.provider === model.provider && ctx.model?.id === model.id;
	}

	/** Switch the session model and thinking level for a phase. */
	async function switchToRole(
		ctx: ExtensionContext,
		role: PhaseRole,
		model: Model<Api>,
	): Promise<boolean> {
		const ok = await pi.setModel(model);
		if (!ok) {
			ctx.ui.notify(
				`No credentials for ${model.provider}/${model.id}; keeping the current model.`,
				"warning",
			);
			return false;
		}
		pi.setThinkingLevel(ROLE_THINKING[role]);
		ctx.ui.notify(`Model: ${role} → ${model.name}`, "info");
		updateStatus(ctx);
		return true;
	}

	/** Back to the model that was active before plan mode started. With
	 *  keepSaved the model is restored but the snapshot is retained — used on the
	 *  isolated-execution path, where a later revise → re-approve cycle still
	 *  needs the orchestrator snapshot for completion. */
	async function restoreOrchestrator(ctx: ExtensionContext, keepSaved = false): Promise<void> {
		const saved = orchestrator;
		if (!saved) return;
		const model = ctx.modelRegistry.find(saved.provider, saved.id);
		if (!model) {
			ctx.ui.notify(
				`Cannot restore ${saved.provider}/${saved.id}; keeping the current model.`,
				"warning",
			);
			return;
		}
		const ok = await pi.setModel(model);
		if (!ok) {
			ctx.ui.notify(`No credentials for ${saved.provider}/${saved.id}; keeping the current model.`, "warning");
			return;
		}
		pi.setThinkingLevel(saved.thinkingLevel);
		// Only forget the saved model once it is actually active again.
		if (!keepSaved) orchestrator = undefined;
		updateStatus(ctx);
	}

	/**
	 * First plan turn: choose the planning model. GLM 5.3 Flash is first (Enter
	 * keeps the workhorse), stronger models are listed for complex work. This
	 * runs in before_agent_start, before the request is built, so the switch
	 * applies to this same turn.
	 */
	async function maybeChoosePlannerModel(ctx: ExtensionContext): Promise<void> {
		if (plannerChosen) return;
		// Ask at most once per plan-mode entry; a dismissed dialog must not block
		// the next turn on the same question.
		plannerChosen = true;
		orchestrator ??= snapshotModel(ctx);

		const candidates = resolveRoleModels(ctx, PLANNER_MODELS);
		if (candidates.length === 0) {
			plannerModel ??= snapshotModel(ctx);
			persistState();
			return;
		}
		// A manual /model pick that is already a planner is honored without a dialog.
		if (candidates.some((candidate) => isCurrentModel(ctx, candidate.model))) {
			plannerModel = snapshotModel(ctx);
			persistState();
			return;
		}
		const defaultPlanner = candidates[0];
		if (!ctx.hasUI) {
			// Print/RPC mode: use the advertised default rather than whatever model
			// happened to be selected.
			if (defaultPlanner && (await switchToRole(ctx, "planner", defaultPlanner.model))) {
				plannerModel = snapshotModel(ctx);
			}
			persistState();
			return;
		}

		const options = uniqueLabels(
			candidates.map((candidate) => describeRoleModel(candidate)),
			candidates,
		);
		const choice = await ctx.ui.select("Plan with which model?", options);
		const picked = choice === undefined ? undefined : candidates[options.indexOf(choice)];
		if (picked) {
			if (await switchToRole(ctx, "planner", picked.model)) plannerModel = snapshotModel(ctx);
		} else {
			// Dismissed: the current model plans, and it is what we return to on a
			// Shift+Tab round-trip from execution.
			plannerModel = snapshotModel(ctx);
		}
		persistState();
	}

	/**
	 * Approval-time pick: the planner's recommendation first (★), otherwise the
	 * workhorse. The planner can recommend isolation for risky or long plans by
	 * writing `Implementer: Isolated (<model id>) — <reason>`, which stars the
	 * isolated option; a plain model recommendation stars the inline path.
	 *
	 * "Isolated — worker subagent" delegates execution to per-step `worker`
	 * subagents. In that mode the session model is NOT switched to the
	 * implementer: the orchestrator keeps its own model (dispatch and failure
	 * recovery are cheap; the worker's model must not constrain them) and each
	 * dispatch carries an explicit `model` override instead.
	 * Dismissing keeps plan mode and runs nothing.
	 */
	async function chooseImplementerModel(
		ctx: ExtensionContext,
	): Promise<{ model: Model<Api>; isolated: boolean } | undefined> {
		const candidates = resolveRoleModels(ctx, IMPLEMENTER_MODELS);
		if (candidates.length === 0) {
			return ctx.model ? { model: ctx.model, isolated: false } : undefined;
		}

		const pickText = (lastImplementerPick?.pick ?? "").replace(/[`*]/g, "").trim();
		const recommendsIsolated = /^isolated/i.test(pickText);
		const innerPick = recommendsIsolated ? pickText.replace(/^isolated/i, "").replace(/[()]/g, " ").trim() : pickText;
		const recommended = innerPick ? matchModelChoice(innerPick, candidates) : undefined;
		const ordered = recommended
			? [recommended, ...candidates.filter((candidate) => candidate !== recommended)]
			: [...candidates];
		if (!ctx.hasUI) {
			const first = ordered[0]?.model;
			return first ? { model: first, isolated: false } : undefined;
		}

		const canDispatch = subagentToolActive();
		const modelLabels = uniqueLabels(
			ordered.map((candidate) => {
				const star = candidate === recommended;
				const reason =
					star && lastImplementerPick?.reason ? ` — planner pick: ${lastImplementerPick.reason}` : "";
				return `${star ? "★ " : "  "}${describeRoleModel(candidate)}${reason}`;
			}),
			ordered,
		);
		const ISOLATED = "Isolated — worker subagent (per-step dispatch)";
		const options =
			canDispatch && recommendsIsolated
				? [`★ ${ISOLATED} — planner pick: ${lastImplementerPick?.reason ?? "risky/long plan"}`, ...modelLabels]
				: [...modelLabels, ...(canDispatch ? [ISOLATED] : [])];

		const choice = await ctx.ui.select("Implement with which model?", options);
		if (choice === undefined) return undefined;

		// The starred isolated label carries a "★ " prefix and a reason suffix, so
		// match on the option body, not an exact/startsWith equality.
		if (choice.includes(ISOLATED)) {
			const modelChoice = await ctx.ui.select("Model for the isolated worker?", modelLabels);
			if (modelChoice === undefined) return undefined;
			const model = ordered[modelLabels.indexOf(modelChoice)]?.model;
			return model ? { model, isolated: true } : undefined;
		}
		const model = ordered[options.indexOf(choice)]?.model;
		return model ? { model, isolated: false } : undefined;
	}

	/**
	 * Reviewer suggestion: GLM 5.3 Flash for small/mechanical work, Opus 5.5 for
	 * risky or repeated reviews, Kimi K3.1 Pro for everything else.
	 */
	function automaticReviewer(candidates: ReturnType<typeof resolveRoleModels>) {
		const byId = (id: string) => candidates.find((candidate) => candidate.model.id === id);
		const risky =
			reviewRound > 1 ||
			todoItems.length >= 6 ||
			implementerModel?.id === "Heavy" ||
			implementerModel?.id === "Claude Opus 5.5";
		if (risky) {
			const opus = byId("Claude Opus 5.5");
			if (opus) return opus;
		}
		const trivial = todoItems.length <= 2 || implementerModel?.id === "GPT-6 Luna";
		if (trivial) {
			const glm = byId("GLM 5.3 Flash");
			if (glm) return glm;
		}
		return candidates[0];
	}

	async function chooseReviewerModel(ctx: ExtensionContext): Promise<Model<Api> | undefined> {
		const candidates = resolveRoleModels(ctx, REVIEWER_MODELS);
		if (candidates.length === 0) return undefined;

		const suggested = automaticReviewer(candidates) ?? candidates[0];
		if (!suggested) return undefined;
		const ordered = [suggested, ...candidates.filter((candidate) => candidate !== suggested)];
		if (!ctx.hasUI) return suggested.model;

		const options = uniqueLabels(
			ordered.map(
				(candidate, index) =>
					`${index === 0 ? "★ " : "  "}${describeRoleModel(candidate)}${index === 0 ? " — suggested" : ""}`,
			),
			ordered,
		);
		const choice = await ctx.ui.select("Review with which model?", options);
		return ordered[choice === undefined ? 0 : options.indexOf(choice)]?.model ?? suggested.model;
	}

	async function completePlan(ctx: ExtensionContext): Promise<void> {
		const completedList = todoItems.map((t) => `~~${t.text}~~`).join("\n");
		pi.sendMessage(
			{ customType: "plan-complete", content: `**Plan Complete!** ✓\n\n${completedList}`, display: true },
			// nextTurn: delivered with the next user prompt instead of triggering an
			// extra (expensive) LLM turn to acknowledge the card.
			{ deliverAs: "nextTurn" },
		);

		executionMode = false;
		reviewing = false;
		awaitingAnswers = false;
		reviewRound = 0;
		mutatedThisExecution = false;
		todoItems = [];
		lastImplementerPick = undefined;
		plannerModel = undefined;
		implementerIsolated = false;
		if (toolsBeforeReview) {
			pi.setActiveTools(toolsBeforeReview);
			toolsBeforeReview = undefined;
		}
		await restoreOrchestrator(ctx);
		updateStatus(ctx);
		persistState(); // Save cleared state so resume doesn't restore old execution mode
	}

	async function beginReview(ctx: ExtensionContext): Promise<void> {
		reviewRound += 1;
		const reviewer = await chooseReviewerModel(ctx);
		if (!reviewer) {
			await completePlan(ctx);
			return;
		}
		if (subagentToolActive()) {
			// Dispatch-phase isolation: the reviewer runs as a subagent with an
			// explicit model; the session keeps its own model for the relay turn.
			reviewerModel = {
				provider: reviewer.provider,
				id: reviewer.id,
				thinkingLevel: ROLE_THINKING.reviewer,
			};
		} else {
			const ok = await switchToRole(ctx, "reviewer", reviewer);
			if (!ok) {
				await completePlan(ctx);
				return;
			}
			reviewerModel = snapshotModel(ctx);
		}
		reviewing = true;
		// Read-only review: a fixed whitelist, not the inherited tool set (custom
		// tools may mutate state). The subagent tool joins the whitelist when the
		// subagent extension is loaded, so the review can be dispatched to the
		// read-only `reviewer` agent in an isolated context.
		toolsBeforeReview ??= pi.getActiveTools();
		pi.setActiveTools(subagentToolActive() ? [...REVIEW_MODE_TOOLS, "subagent"] : REVIEW_MODE_TOOLS);
		persistState();

		const planList = todoItems.map((t) => `${t.step}. ${t.text}`).join("\n");
		const reviewerModelKey = reviewerModel ? modelKey({ provider: reviewerModel.provider, id: reviewerModel.id }) : "";
		const reviewHow = subagentToolActive()
			? `Dispatch the review to the read-only \`reviewer\` subagent instead of reviewing inline:

subagent { "agent": "reviewer", "model": "${reviewerModelKey}", "task": "<review brief>" }

Always pass the "model" override shown above — the reviewer must not silently inherit a different model.
The subagent ends with \`Verdict: CLEAN\` or \`Verdict: FINDINGS (n)\`. Relay its verdict in your own response by mapping: CLEAN → \`Verdict: APPROVED\`; FINDINGS (n) → \`Verdict: CHANGES NEEDED\` followed by the findings as bullets. Never end your own response with CLEAN or FINDINGS.

The subagent cannot see this conversation, so the brief must be self-contained:
- The plan being reviewed:
${planList}
- What to review: the working tree against these plan steps. Run git status and git diff; read untracked files directly; read the changed files around each change (correctness, edge cases, error handling, security, tests, and whether each plan step is actually implemented).
- The subagent must end with exactly one line: \`Verdict: CLEAN\` or \`Verdict: FINDINGS (n)\` with the blocking findings listed (file:line, what is wrong, what to change).

Only the read-only reviewer agents (\`reviewer\`, \`reviewer-strong\`) may be dispatched, and you must not edit files yourself. When the subagent result returns, relay its verdict in your own response.`
			: `- Run \`git status\` and \`git diff\`; read untracked files directly.
- Read the changed files around each change: correctness, edge cases, error handling, security, tests, and whether each plan step is actually implemented.
- Do NOT edit files. Report findings only.`;

		pi.sendMessage(
			{
				customType: "plan-review",
				content: `[REVIEWING IMPLEMENTATION — read-only]

All plan steps are marked done. Review the implementation in the working tree against the plan in this conversation.

${reviewHow}

End your response with exactly one of these lines:
Verdict: APPROVED
Verdict: CHANGES NEEDED

When changes are needed, follow the verdict with a bullet list of concrete findings (file:line, what is wrong, what to change).`,
				display: true,
			},
			{ triggerTurn: true, deliverAs: "followUp" },
		);
	}

	async function handleReviewOutcome(
		ctx: ExtensionContext,
		lastAssistant: AssistantMessage | undefined,
	): Promise<void> {
		const verdict = lastAssistant ? extractReviewVerdict(getContentBlocks(lastAssistant)) : undefined;
		if (!verdict) {
			// A reviewer that ignores the contract must not loop forever.
			ctx.ui.notify("Reviewer did not emit a verdict — finishing without a review gate.", "warning");
			await completePlan(ctx);
			return;
		}
		if (verdict.approved) {
			await completePlan(ctx);
			return;
		}
		if (reviewRound >= MAX_REVIEW_ROUNDS) {
			pi.sendMessage(
				{
					customType: "plan-review-report",
					content: `**Review still requests changes after ${reviewRound} round(s).**\n\n${verdict.findings.map((finding) => `- ${finding}`).join("\n") || "(no findings listed)"}`,
					display: true,
				},
				{ deliverAs: "nextTurn" },
			);
			await completePlan(ctx);
			return;
		}

		// Hand the findings back to the implementer; the next finished turn
		// triggers another review pass. Restore tools before persisting so a crash
		// cannot leave review-only tools active in a non-review state.
		if (toolsBeforeReview) {
			pi.setActiveTools(toolsBeforeReview);
			toolsBeforeReview = undefined;
		}
		reviewing = false;
		persistState();
		const implementer =
			(implementerModel && ctx.modelRegistry.find(implementerModel.provider, implementerModel.id)) ??
			resolveRoleModels(ctx, IMPLEMENTER_MODELS)[0]?.model;
		if (implementer && !implementerIsolated) {
			// Inline mode: the fix turn runs on the implementer model. Isolated mode
			// keeps the orchestrator's model — the fix dispatch carries the worker's
			// model explicitly (see the fix message below).
			await switchToRole(ctx, "implementer", implementer);
		}
		updateStatus(ctx);

		const findings = verdict.findings.map((finding) => `- ${finding}`).join("\n");
		const workerModel = implementerModel ? modelKey({ provider: implementerModel.provider, id: implementerModel.id }) : "";
		const fixHow = implementerIsolated
			? `Delegate each fix to the \`worker\` subagent — do not implement fixes inline. Dispatch with { "agent": "worker", "model": "${workerModel}", "task": "<self-contained fix brief>" }; the brief cannot see this conversation, so include the finding, the file and line, and what to change.`
			: `Fix each finding now.`;
		pi.sendMessage(
			{
				customType: "plan-review-fixes",
				content: `[REVIEW CHANGES REQUESTED]\n\nThe reviewer (${reviewerModel?.id ?? "reviewer"}) found issues with the implementation:\n\n${findings || "(no findings listed)"}\n\n${fixHow} Do not restate the plan; make the changes and leave the plan steps complete so the review can run again.`,
				display: true,
			},
			{ triggerTurn: true, deliverAs: "followUp" },
		);
	}

	function persistState(): void {
		pi.appendEntry("plan-mode", {
			enabled: planModeEnabled,
			todos: todoItems,
			executing: executionMode,
			awaitingAnswers,
			toolsBeforePlanMode,
			plannerChosen,
			planner: plannerModel,
			orchestrator,
			implementer: implementerModel,
			implementerIsolated,
			reviewer: reviewerModel,
			reviewing,
			reviewRound,
			toolsBeforeReview,
			mutated: mutatedThisExecution,
		});
	}

	async function togglePlanMode(ctx: ExtensionContext): Promise<void> {
		// Leaving a review restores the full tool set before either mode narrows
		// it, and before `enablePlanModeTools` snapshots the "before" set.
		if (toolsBeforeReview) {
			pi.setActiveTools(toolsBeforeReview);
			toolsBeforeReview = undefined;
		}
		planModeEnabled = !planModeEnabled;
		executionMode = false;
		awaitingAnswers = false;
		reviewing = false;
		todoItems = [];
		plannerChosen = false;
		lastImplementerPick = undefined;
		reviewRound = 0;
		plannerModel = undefined;
		implementerIsolated = false;

		if (planModeEnabled) {
			enablePlanModeTools();
			ctx.ui.notify("Plan mode enabled. Built-in write tools disabled.");
		} else {
			restoreNormalModeTools();
			await restoreOrchestrator(ctx);
			ctx.ui.notify("Plan mode disabled. Full access restored.");
		}
		updateStatus(ctx);
		persistState();
	}

	async function enterPlanMode(ctx: ExtensionContext): Promise<void> {
		const fromExecution = executionMode;
		planModeEnabled = true;
		executionMode = false;
		awaitingAnswers = false;
		// Leaving a review restores the full tool set before plan mode narrows it.
		if (toolsBeforeReview) {
			pi.setActiveTools(toolsBeforeReview);
			toolsBeforeReview = undefined;
		}
		if (!fromExecution) {
			plannerChosen = false;
			lastImplementerPick = undefined;
			reviewRound = 0;
			plannerModel = undefined;
		} else if (plannerModel) {
			// Re-entering plan mode from execution: plan revisions belong to the
			// planner, not the implementer that is currently selected.
			const planner = ctx.modelRegistry.find(plannerModel.provider, plannerModel.id);
			if (planner) await switchToRole(ctx, "planner", planner);
		}
		reviewing = false;
		enablePlanModeTools();
		updateStatus(ctx);
		persistState();
	}

	/**
	 * Execute mode: plan mode off, every previously active tool restored, and no
	 * bash allowlist — the tool_call gate below only runs while planModeEnabled.
	 */
	function beginExecution(ctx: ExtensionContext): void {
		planModeEnabled = false;
		executionMode = true;
		awaitingAnswers = false;
		reviewing = false;
		reviewRound = 0;
		mutatedThisExecution = false;
		restoreNormalModeTools();
		updateStatus(ctx);
		persistState();
	}

	// Local deviation from upstream: a tool the agent calls to tick plan steps
	// immediately, mid-turn, instead of waiting for [DONE:n] tags to be parsed at
	// message end (which made the progress widget jump 0 -> all at once).
	pi.registerTool({
		name: "plan_done",
		label: "Plan step done",
		description:
			"Mark one or more plan steps as completed. Call this tool immediately after finishing each plan step (e.g. {\"steps\":[1]}). Also include a [DONE:n] tag in your text as a backup.",
		promptSnippet: "Report completed plan-step numbers during plan execution",
		promptGuidelines: [
			"When executing a plan, call plan_done with the finished step number(s) right after completing each step.",
		],
		parameters: Type.Object({
			steps: Type.Array(Type.Number({ description: "Plan step number(s) that are now complete" })),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			if (!executionMode || todoItems.length === 0) {
				return {
					content: [{ type: "text", text: "No plan execution in progress; step not recorded." }],
					details: {},
				};
			}
			const marked: number[] = [];
			for (const n of params.steps) {
				const item = todoItems.find((t) => t.step === n);
				if (item && !item.completed) {
					item.completed = true;
					marked.push(n);
				}
			}
			const completed = todoItems.filter((t) => t.completed).length;
			if (marked.length > 0) {
				updateStatus(ctx);
				persistState();
			}
			const text =
				marked.length > 0
					? `Marked step(s) ${marked.join(", ")} done. Progress: ${completed}/${todoItems.length}.`
					: `No change: ${completed}/${todoItems.length} steps already complete.`;
			return { content: [{ type: "text", text }], details: { marked } };
		},
	});

	const APPROVE = "Approve — implement now";
	const REVISE = "Revise plan…";

	/**
	 * Claude Code-style approval gate: show the plan, ask permission, and repeat
	 * (revise -> re-plan -> ask again) until the user approves.
	 */
	async function requestPlanApproval(ctx: ExtensionContext): Promise<void> {
		if (todoItems.length === 0) return;

		const todoListText = todoItems.map((t, i) => `${i + 1}. ☐ ${t.text}`).join("\n");
		const planTodoListMessage = {
			customType: "plan-todo-list",
			content: `**Plan Steps (${todoItems.length}):**\n\n${todoListText}`,
			display: true,
		};

		const choice = await ctx.ui.select(`Approve this plan? (${todoItems.length} steps)`, [APPROVE, REVISE]);

		if (choice === APPROVE) {
			const firstTodoItem = todoItems[0];
			if (!firstTodoItem) return;

			// Model pick for implementation: the planner's recommendation first,
			// otherwise the workhorse. Dismissing keeps plan mode and runs nothing.
			const implementer = await chooseImplementerModel(ctx);
			if (!implementer) {
				ctx.ui.notify("No implementer selected — staying in plan mode.", "info");
				return;
			}
			if (implementer.isolated) {
				// The orchestrator keeps its own model: each worker dispatch carries
				// an explicit model override, so the session never runs on the
				// implementer model during the (cheap) dispatch phase.
				implementerModel = {
					provider: implementer.model.provider,
					id: implementer.model.id,
					thinkingLevel: ROLE_THINKING.implementer,
				};
				implementerIsolated = true;
				// keepSaved: completion must still be able to restore the orchestrator
				// after a revise → re-approve-inline round-trip.
				await restoreOrchestrator(ctx, true);
				beginExecution(ctx);
				ctx.ui.notify(
					`Isolated implementer: worker subagents on ${modelKey(implementer.model)}; orchestrator keeps its own model.`,
					"info",
				);
			} else {
				if (!(await switchToRole(ctx, "implementer", implementer.model))) {
					ctx.ui.notify("Implementer switch failed — staying in plan mode.", "warning");
					return;
				}
				implementerModel = snapshotModel(ctx);
				implementerIsolated = false;
				beginExecution(ctx);
			}

			const remainingList = todoItems.map((t) => `${t.step}. ${t.text}`).join("\n");
			const workerModel = modelKey(implementer.model);
			const how = implementer.isolated
				? `Execute the plan by delegating each step to the \`worker\` subagent — do not implement the steps yourself.

For each remaining step, in order:
1. Dispatch subagent with { "agent": "worker", "model": "${workerModel}", "task": "<self-contained brief>" }.
   The subagent cannot see this conversation: the brief must carry the step text, the plan context it
   needs (intent, files, constraints), and the relevant verification to run. Always pass the
   "model" override shown above — the worker must not silently inherit a different model.
2. When the result returns, call plan_done with that step's number (e.g. {"steps":[2]}).
3. If the worker did not complete the step, re-dispatch once with the failure context; if it
   fails again, stop and report — never mark a failed step done.

After the last step, summarize what was implemented.`
				: `Start with: ${firstTodoItem.text}
After completing each step, call the plan_done tool with that step's number immediately (e.g. {"steps":[1]}), and also include a [DONE:n] tag in your text as a backup.`;
			const execMessage = `Execute the plan.

Remaining steps:
${remainingList}

${how}`;
			pi.sendMessage(planTodoListMessage, { deliverAs: "followUp" });
			pi.sendMessage(
				{ customType: "plan-mode-execute", content: execMessage, display: true },
				{ triggerTurn: true, deliverAs: "followUp" },
			);
			return;
		}

		if (choice === REVISE) {
			awaitingAnswers = false;
			const refinement = await ctx.ui.editor("What should change in the plan?", "");
			if (refinement?.trim()) {
				// Local deviation from upstream: guardrails so the revise turn edits
				// the plan instead of re-exploring the codebase from scratch.
				const guarded = `[PLAN REVISION — do NOT execute anything; do NOT run any tools that modify files or state. Present the revised plan and wait for the approval dialog] Apply the feedback below to the existing numbered plan. You already explored the codebase while planning — do NOT re-read files, re-run searches, or re-explore unless the feedback specifically requires verification. Output only the revised full plan in the same "Plan:" numbered format, and keep unchanged steps as-is.\n\nFeedback: ${refinement.trim()}`;
				pi.sendMessage(planTodoListMessage, { deliverAs: "followUp" });
				pi.sendUserMessage(guarded, { deliverAs: "followUp" });
			}
			return;
		}

		// KEEP_PLANNING was removed: it was a no-op fallthrough identical to
		// dismissing the dialog. Dismissal (Esc/undefined) keeps plan mode; the
		// next plan the agent presents asks again.
	}

	pi.registerCommand("plan", {
		description: "Toggle plan mode (read-only exploration)",
		handler: async (_args, ctx) => {
			await togglePlanMode(ctx);
		},
	});

	pi.registerCommand("todos", {
		description: "Show current plan todo list",
		handler: async (_args, ctx) => {
			if (todoItems.length === 0) {
				ctx.ui.notify("No todos. Create a plan first with /plan", "info");
				return;
			}

			if (ctx.mode !== "tui") {
				const list = todoItems.map((item) => `${item.step}. ${item.completed ? "✓" : "○"} ${item.text}`).join("\n");
				ctx.ui.notify(`Plan Progress:\n${list}`, "info");
				return;
			}

			await ctx.ui.custom<void>(
				(tui, theme, keybindings, done) => createTodoOverlay(todoItems, { tui, theme, keybindings, done }),
				{
					overlay: true,
					overlayOptions: {
						width: "80%",
						maxHeight: OVERLAY_PAGE_ROWS + 5,
						anchor: "center",
						margin: 2,
					},
					blocked: { kind: "question", message: "Plan todo list" },
				},
			);
		},
	});

	pi.registerShortcut(Key.ctrlAlt("p"), {
		description: "Toggle plan mode",
		handler: async (ctx) => {
			await togglePlanMode(ctx);
		},
	});

	// Shift+Tab flips between planning and executing. Pi reserves Shift+Tab for
	// app.thinking.cycle, so ~/.pi/agent/keybindings.json must move that binding
	// (pi/keybindings.json does it, linked by setup-dev-env.sh). Otherwise Pi
	// skips this shortcut with a conflict warning.
	pi.registerShortcut("shift+tab", {
		description: "Switch plan mode <-> execute mode",
		handler: async (ctx) => {
			if (executionMode) {
				await enterPlanMode(ctx);
				ctx.ui.notify("⏸ Plan mode (read-only). Shift+Tab to execute again.");
				return;
			}

			if (!planModeEnabled) {
				await enterPlanMode(ctx);
				ctx.ui.notify("⏸ Plan mode (read-only). Shift+Tab to review the plan.");
				return;
			}

			if (todoItems.length === 0) {
				// Nothing to approve yet: Shift+Tab leaves plan mode instead of
				// pretending to execute an empty plan.
				planModeEnabled = false;
				plannerChosen = false;
				lastImplementerPick = undefined;
				restoreNormalModeTools();
				await restoreOrchestrator(ctx);
				updateStatus(ctx);
				persistState();
				ctx.ui.notify("No plan yet — left plan mode. Full access restored.");
				return;
			}

			// A plan exists, so Shift+Tab asks for permission instead of jumping
			// straight into execute mode. Rejection keeps the plan loop going.
			if (!ctx.isIdle()) {
				ctx.ui.notify("Finish the current turn before approving the plan.", "info");
				return;
			}
			await requestPlanApproval(ctx);
		},
	});

	// Bash stays read-only in plan mode and during the review pass. Execute mode
	// otherwise has full access to every command. Subagent dispatches are gated
	// too: a subagent runs with its own tool set, so dispatching a mutating agent
	// (worker) would bypass the read-only guarantee entirely.
	pi.on("tool_call", async (event) => {
		const restricted = reviewing || (planModeEnabled && !executionMode);
		if (!restricted) return;
		if (event.toolName === "subagent") {
			const agent = (event.input as { agent?: string }).agent;
			const allowed = reviewing
				? agent === "reviewer" || agent === "reviewer-strong"
				: agent !== undefined && READONLY_AGENTS.has(agent);
			if (!allowed) {
				return {
					block: true,
					reason: reviewing
						? "Review mode: only the read-only `reviewer` agent may be dispatched."
						: "Plan mode: only read-only agents (scout, reviewer) may be dispatched — the worker agent can modify files.",
					};
			}
			return;
		}
		if (event.toolName !== "bash") return;

		const command = event.input.command as string;
		if (!isSafeCommand(command)) {
			return {
				block: true,
				reason: reviewing
					? `Review mode: only read-only commands are allowed.\nCommand: ${command}`
					: `Plan mode: command blocked (not allowlisted). Use /plan to disable plan mode first.\nCommand: ${command}`,
			};
		}
	});

	// Track mutations during execution so a planning-only plan can skip review.
	pi.on("tool_result", async (event) => {
		if (!executionMode || reviewing || event.isError || mutatedThisExecution) return;
		const command = (event.input as { command?: string }).command ?? "";
		const mutating =
			event.toolName === "edit" ||
			event.toolName === "write" ||
			// A dispatched worker's file changes happen in a child process and are
			// not visible to this hook, so any subagent run during execution counts
			// as mutating (a read-only dispatch just triggers an unneeded review —
			// the safe direction).
			event.toolName === "subagent" ||
			(event.toolName === "bash" && !isSafeCommand(command));
		if (mutating) {
			mutatedThisExecution = true;
			persistState();
		}
	});

	// Filter out stale plan/review context when that phase is over.
	pi.on("context", async (event) => {
		if (planModeEnabled || reviewing) return;

		return {
			messages: event.messages.filter((m) => {
				const msg = m as AgentMessage & { customType?: string };
				if (msg.customType === "plan-mode-context") return false;
				// The injected review context is only valid while reviewing; the
				// trigger/fix messages stay for the review and fix turns, then go.
				if (msg.customType === "plan-review-context") return false;
				if (msg.customType === "plan-review" || msg.customType === "plan-review-fixes") {
					return executionMode;
				}
				if (msg.role !== "user") return true;

				const content = msg.content;
				if (typeof content === "string") {
					return !content.includes("[PLAN MODE ACTIVE]");
				}
				if (Array.isArray(content)) {
					return !content.some(
						(c) => c.type === "text" && (c as TextContent).text?.includes("[PLAN MODE ACTIVE]"),
					);
				}
				return true;
			}),
		};
	});

	// Inject plan/execution context before a user prompt. Runs started by custom messages, such as
	// background task notifications, skip it: the context from the last prompt is still in the
	// conversation, and adding it again on every notification would only repeat it.
	pi.on("before_agent_start", async (event, ctx) => {
		if (event.messageType !== "user") return;

		if (planModeEnabled) {
			// Runs before the request is built, so the planner model applies to this
			// same turn. Asks once per plan-mode entry.
			await maybeChoosePlannerModel(ctx);

			const awaitingNote = awaitingAnswers
				? `\nYour clarifying questions have been answered. Now present the full plan
under a "Plan:" header. Ask follow-up questions only if something is still
genuinely blocking a sensible plan — otherwise do not ask again.`
				: "";
			const implementerMenu = resolveRoleModels(ctx, IMPLEMENTER_MODELS)
				.map(
					(candidate) =>
						`- ${candidate.model.id} — ${formatModelCost(candidate.model)} — ${candidate.note}`,
				)
				.join("\n");
			if (awaitingAnswers) {
				// The user's reply to our clarifying questions just arrived; the note
				// above tells the agent to plan now. Clear so later turns don't keep
				// repeating it.
				awaitingAnswers = false;
				persistState();
			}
			return {
				message: {
					customType: "plan-mode-context",
					content: `[PLAN MODE ACTIVE]
You are in plan mode - a read-only exploration mode for safe code analysis.

Restrictions:
- Built-in edit and write tools are disabled
- Other currently active tools remain available
- Bash is restricted to an allowlist of read-only commands${awaitingNote}

Work in two phases — NEVER both in the same response:

Phase 1 — Clarify (only if the request is ambiguous or missing key details):
Call the questionnaire tool with option-based questions (each option needs a
value, a label, and an optional description). Begin the response with the
header "Clarifying questions:" followed by a one-line summary of what you are
asking and why. Do NOT present a plan before the questions are answered. If
you asked plain-text questions instead of using the tool, end your turn and
wait for the user's reply. If the request is already clear enough to plan,
skip this phase.

Phase 2 — Plan (when requirements are clear, or answers have arrived):
When the questionnaire tool returns the user's answers as its result,
continue straight into this phase in the same turn — no extra round-trip is
needed. Explore the codebase read-only as needed, then output the full plan:

Plan:
1. First step description
2. Second step description
...

When you present a "Plan:" section, do NOT also ask clarifying questions in
that response — ask them in a separate earlier turn instead.

When the user asks for plan changes, revise the plan text only — do not
execute it and do not re-explore the codebase unless the change requires
verification.

A revision request is NEVER approval. After producing a revised plan, stop and
wait for the approval dialog. Only "Approve — implement now" in the dialog, or
the user explicitly saying "approve" or "implement", starts execution. Presenting
a revised plan — even in response to the user restating the plan steps — does not
grant permission to run anything.

Before you stop, add exactly one unnumbered line after the plan, outside any
code fence:

Implementer: <model id> — <one-line reason>

Choose from the implementation models by difficulty. Use GPT-6 Luna for trivial,
mechanical changes, GLM 5.3 Flash for ordinary work, and a stronger model when
the plan is risky or cross-cutting. For risky, long, or context-heavy plans,
recommend isolated execution instead: write the line as
Implementer: Isolated (<model id>) — <reason>
(the word Isolated, then the worker's model id in parentheses) — the picker
then offers the per-step worker-subagent dispatch first, with the orchestrator
keeping its own model. The user confirms the pick before anything runs.

Implementation models:
${implementerMenu}

Do NOT attempt to make changes - just describe what you would do. Then stop and
wait: the user approves, keeps planning, or asks for a revision, and every
revised plan is presented for approval again.`,
					display: false,
				},
			};
		}

		if (reviewing && todoItems.length > 0) {
			return {
				message: {
					customType: "plan-review-context",
					content: `[REVIEWING IMPLEMENTATION — read-only]

${subagentToolActive()
	? `All plan steps are done. Review the implementation in the working tree against the plan in this conversation — via the read-only \`reviewer\` subagent, not inline:

subagent { "agent": "reviewer", "model": "${reviewerModel ? modelKey({ provider: reviewerModel.provider, id: reviewerModel.id }) : ""}", "task": "<review brief>" }

The brief must be self-contained (the subagent cannot see this conversation) and must include the plan steps:
${todoItems.map((t) => `${t.step}. ${t.text}`).join("\n")}
The subagent ends with \`Verdict: CLEAN\` or \`Verdict: FINDINGS (n)\`; relay its verdict by mapping CLEAN → \`Verdict: APPROVED\` and FINDINGS (n) → \`Verdict: CHANGES NEEDED\` with the findings as bullets. Only the read-only reviewer agents may be dispatched; do not edit files yourself.`
	: `All plan steps are done. Review the implementation in the working tree against the plan in this conversation. Do NOT edit files.`}

End your response with exactly one of these lines:
Verdict: APPROVED
Verdict: CHANGES NEEDED

When changes are needed, follow the verdict with a bullet list of concrete findings (file:line, what is wrong, what to change).`,
					display: false,
				},
			};
		}

		if (executionMode && todoItems.length > 0) {
			const remaining = todoItems.filter((t) => !t.completed);
			const todoList = remaining.map((t) => `${t.step}. ${t.text}`).join("\n");
			const how = implementerIsolated
				? `Execute each remaining step by delegating it to the \`worker\` subagent (self-contained brief — the subagent cannot see this conversation), then call plan_done with that step's number. Re-dispatch a failed step once; never mark a failed step done. Do not implement steps yourself.`
				: `Execute each step in order.
Every tool and every bash command is available; nothing is restricted in execute mode.
After completing each step, call the plan_done tool with that step's number immediately (e.g. {"steps":[1]}), and also include a [DONE:n] tag in your text as a backup.`;
			return {
				message: {
					customType: "plan-execution-context",
					content: `[EXECUTING PLAN - Full tool access enabled]

Remaining steps:
${todoList}

${how}`,
					display: false,
				},
			};
		}
	});

	// Track progress after each turn
	pi.on("turn_end", async (event, ctx) => {
		if (!executionMode || todoItems.length === 0) return;
		if (!isAssistantMessage(event.message)) return;

		markCompletedSteps(getTextContent(event.message), todoItems);
		// Always refresh: cheap, keeps the widget consistent even when nothing matched.
		updateStatus(ctx);
		persistState();
	});

	// Handle plan completion and plan mode UI
	pi.on("agent_end", async (event, ctx) => {
		// Check if execution is complete
		if (executionMode && todoItems.length > 0) {
			const lastAssistant = [...event.messages].reverse().find(isAssistantMessage);

			// Esc reaches agent_end too. Keep the phase intact so the user can retry
			// instead of completing or reviewing a half-finished turn.
			if (lastAssistant?.stopReason === "aborted") return;

			// A finished review turn either approves the work or sends findings
			// back to the implementer; it never falls through to a plain completion.
			if (reviewing) {
				await handleReviewOutcome(ctx, lastAssistant);
				return;
			}

			// Fallback: the model wrapped up without [DONE:n] tags ("All steps complete").
			if (lastAssistant && allStepsComplete(getTextContent(lastAssistant))) {
				for (const t of todoItems) t.completed = true;
			}
			if (!todoItems.every((t) => t.completed)) return;

			// Nothing was mutated (planning-only plan): finish without paying for a
			// reviewer. After a changes-requested round, always re-review.
			if (reviewRound === 0 && !mutatedThisExecution) {
				await completePlan(ctx);
				return;
			}

			await beginReview(ctx);
			return;
		}

		if (!planModeEnabled || !ctx.hasUI) return;

		// Extract todos from last assistant message
		const lastAssistant = [...event.messages].reverse().find(isAssistantMessage);
		let extracted: TodoItem[] = [];
		if (lastAssistant) {
			const blocks = getContentBlocks(lastAssistant);
			extracted = extractTodoItemsFromBlocks(blocks);
			if (extracted.length > 0) {
				todoItems = extracted;
				// Re-parse on every plan so a revision that drops the line clears
				// the previous recommendation instead of inheriting it.
				lastImplementerPick = extractImplementerPick(blocks);
			}
		}

		// Clarify-first gate: when this turn asked the user questions WITHOUT
		// producing a plan (plain-text questions, or a questionnaire call the model
		// didn't plan from), wait for the answers instead of showing the approval
		// dialog. When the questionnaire's in-turn answers already led to a plan,
		// fall through to the normal approval flow — extracting first is what makes
		// that distinction (a run-scoped check alone would suppress the dialog
		// every time the tool was used).
		const askedQuestions =
			event.messages.some(
				(m) =>
					(m as { role?: string; toolName?: string }).role === "toolResult" &&
					(m as { toolName?: string }).toolName === "questionnaire",
			) ||
			(lastAssistant !== undefined &&
				/^#{0,6}\s*\*{0,2}Clarifying questions:?/im.test(getTextContent(lastAssistant)));
		if (askedQuestions && extracted.length === 0) {
			awaitingAnswers = true;
			updateStatus(ctx);
			persistState();
			return;
		}
		awaitingAnswers = false;
		// Refresh the footer here: without this, clearing awaitingAnswers leaves a
		// stale "⏳ awaiting answers" visible even though the approval dialog fires.
		updateStatus(ctx);

		if (todoItems.length === 0) return;
		persistState();

		// Ask permission again on every plan the agent presents. Refining sends
		// the revision as a follow-up, so the loop repeats until approved.
		await requestPlanApproval(ctx);
	});

	// Restore state on session start/resume
	pi.on("session_start", async (_event, ctx) => {
		if (pi.getFlag("plan") === true) {
			planModeEnabled = true;
		}

		const entries = ctx.sessionManager.getEntries();

		// Restore persisted state
		const planModeEntry = entries
			.filter((e: { type: string; customType?: string }) => e.type === "custom" && e.customType === "plan-mode")
			.pop() as { data?: PlanModeState } | undefined;

		if (planModeEntry?.data) {
			planModeEnabled = planModeEntry.data.enabled ?? planModeEnabled;
			todoItems = planModeEntry.data.todos ?? todoItems;
			executionMode = planModeEntry.data.executing ?? executionMode;
			awaitingAnswers = planModeEntry.data.awaitingAnswers ?? awaitingAnswers;
			toolsBeforePlanMode = planModeEntry.data.toolsBeforePlanMode ?? toolsBeforePlanMode;
			plannerChosen = planModeEntry.data.plannerChosen ?? plannerChosen;
			plannerModel = planModeEntry.data.planner ?? plannerModel;
			orchestrator = planModeEntry.data.orchestrator ?? orchestrator;
			implementerModel = planModeEntry.data.implementer ?? implementerModel;
			implementerIsolated = planModeEntry.data.implementerIsolated ?? implementerIsolated;
			reviewerModel = planModeEntry.data.reviewer ?? reviewerModel;
			reviewing = planModeEntry.data.reviewing ?? reviewing;
			reviewRound = planModeEntry.data.reviewRound ?? reviewRound;
			toolsBeforeReview = planModeEntry.data.toolsBeforeReview ?? toolsBeforeReview;
			mutatedThisExecution = planModeEntry.data.mutated ?? mutatedThisExecution;
		}

		// On resume: re-scan messages to rebuild completion state
		// Only scan messages AFTER the last "plan-mode-execute" to avoid picking up [DONE:n] from previous plans
		const isResume = planModeEntry !== undefined;
		if (isResume && executionMode && todoItems.length > 0) {
			// Find the index of the last plan-mode-execute entry (marks when current execution started)
			let executeIndex = -1;
			for (let i = entries.length - 1; i >= 0; i--) {
				const entry = entries[i] as { type: string; customType?: string };
				if (entry.customType === "plan-mode-execute") {
					executeIndex = i;
					break;
				}
			}

			// Only scan messages after the execute marker
			const messages: AssistantMessage[] = [];
			for (let i = executeIndex + 1; i < entries.length; i++) {
				const entry = entries[i];
				if (entry.type === "message" && "message" in entry && isAssistantMessage(entry.message as AgentMessage)) {
					messages.push(entry.message as AssistantMessage);
				}
			}
			const allText = messages.map(getTextContent).join("\n");
			markCompletedSteps(allText, todoItems);
		}

		if (reviewing) {
			// Resume mid-review: the reviewer keeps the fixed read-only tool set.
			toolsBeforeReview ??= getNormalModeTools(REVIEW_MODE_TOOLS);
			pi.setActiveTools(subagentToolActive() ? [...REVIEW_MODE_TOOLS, "subagent"] : REVIEW_MODE_TOOLS);
		} else if (planModeEnabled) {
			enablePlanModeTools();
		} else if (toolsBeforeReview) {
			// Crash between restoring tools and persisting state: repair on resume.
			pi.setActiveTools(toolsBeforeReview);
			toolsBeforeReview = undefined;
		}
		updateStatus(ctx);
	});

	// Keep the footer honest when the model is switched manually mid-phase.
	pi.on("model_select", async (_event, ctx) => {
		if (planModeEnabled || executionMode) updateStatus(ctx);
	});
}
