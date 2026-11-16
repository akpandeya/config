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
 * - Progress tracking widget during execution
 */

import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { AssistantMessage, TextContent } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { Key } from "@earendil-works/pi-tui";
import { allStepsComplete, extractTodoItems, isSafeCommand, markCompletedSteps, type TodoItem } from "./utils.ts";

// Tools
const PLAN_MODE_TOOLS = ["read", "bash", "grep", "find", "ls", "questionnaire"];
const NORMAL_MODE_TOOLS = ["read", "bash", "edit", "write", "plan_done"];
// plan_done is excluded in plan mode so the model can't tick steps early; it is
// only active during execution, where it marks steps done immediately.
const PLAN_MODE_DISABLED_TOOLS = new Set<string>(["edit", "write", "plan_done"]);
const PLAN_MANAGED_TOOLS = new Set<string>([...PLAN_MODE_TOOLS, ...NORMAL_MODE_TOOLS]);

interface PlanModeState {
	enabled: boolean;
	todos?: TodoItem[];
	executing?: boolean;
	toolsBeforePlanMode?: string[];
}

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

export default function planModeExtension(pi: ExtensionAPI): void {
	let planModeEnabled = false;
	let executionMode = false;
	let todoItems: TodoItem[] = [];
	let toolsBeforePlanMode: string[] | undefined;

	pi.registerFlag("plan", {
		description: "Start in plan mode (read-only exploration)",
		type: "boolean",
		default: false,
	});

	function updateStatus(ctx: ExtensionContext): void {
		// Footer status
		if (executionMode && todoItems.length > 0) {
			const completed = todoItems.filter((t) => t.completed).length;
			ctx.ui.setStatus("plan-mode", ctx.ui.theme.fg("accent", `📋 ${completed}/${todoItems.length}`));
		} else if (planModeEnabled) {
			ctx.ui.setStatus("plan-mode", ctx.ui.theme.fg("warning", "⏸ plan"));
		} else {
			ctx.ui.setStatus("plan-mode", undefined);
		}

		// Widget showing todo list
		if (executionMode && todoItems.length > 0) {
			const lines = todoItems.map((item) => {
				const text = item.text.length > 60 ? `${item.text.slice(0, 57)}...` : item.text;
				if (item.completed) {
					return ctx.ui.theme.fg("success", "☑ ") + ctx.ui.theme.fg("muted", ctx.ui.theme.strikethrough(text));
				}
				return `${ctx.ui.theme.fg("muted", "☐ ")}${text}`;
			});
			ctx.ui.setWidget("plan-todos", lines);
		} else {
			ctx.ui.setWidget("plan-todos", undefined);
		}
	}

	function uniqueToolNames(toolNames: string[]): string[] {
		return [...new Set(toolNames)];
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

	function persistState(): void {
		pi.appendEntry("plan-mode", {
			enabled: planModeEnabled,
			todos: todoItems,
			executing: executionMode,
			toolsBeforePlanMode,
		});
	}

	function togglePlanMode(ctx: ExtensionContext): void {
		planModeEnabled = !planModeEnabled;
		executionMode = false;
		todoItems = [];

		if (planModeEnabled) {
			enablePlanModeTools();
			ctx.ui.notify("Plan mode enabled. Built-in write tools disabled.");
		} else {
			restoreNormalModeTools();
			ctx.ui.notify("Plan mode disabled. Full access restored.");
		}
		updateStatus(ctx);
		persistState();
	}

	function enterPlanMode(ctx: ExtensionContext): void {
		planModeEnabled = true;
		executionMode = false;
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
	const KEEP_PLANNING = "Keep planning";
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

		const choice = await ctx.ui.select(`Approve this plan? (${todoItems.length} steps)`, [
			APPROVE,
			KEEP_PLANNING,
			REVISE,
		]);

		if (choice === APPROVE) {
			const firstTodoItem = todoItems[0];
			if (!firstTodoItem) return;

			beginExecution(ctx);

			const remainingList = todoItems.map((t) => `${t.step}. ${t.text}`).join("\n");
			const execMessage = `Execute the plan.

Remaining steps:
${remainingList}

Start with: ${firstTodoItem.text}
After completing each step, call the plan_done tool with that step's number immediately (e.g. {"steps":[1]}), and also include a [DONE:n] tag in your text as a backup.`;
			pi.sendMessage(planTodoListMessage, { deliverAs: "followUp" });
			pi.sendMessage(
				{ customType: "plan-mode-execute", content: execMessage, display: true },
				{ triggerTurn: true, deliverAs: "followUp" },
			);
			return;
		}

		if (choice === REVISE) {
			const refinement = await ctx.ui.editor("What should change in the plan?", "");
			if (refinement?.trim()) {
				pi.sendMessage(planTodoListMessage, { deliverAs: "followUp" });
				pi.sendUserMessage(refinement.trim(), { deliverAs: "followUp" });
			}
			return;
		}

		// KEEP_PLANNING, or the dialog was dismissed: stay in plan mode. The next
		// plan the agent presents asks again.
	}

	pi.registerCommand("plan", {
		description: "Toggle plan mode (read-only exploration)",
		handler: async (_args, ctx) => togglePlanMode(ctx),
	});

	pi.registerCommand("todos", {
		description: "Show current plan todo list",
		handler: async (_args, ctx) => {
			if (todoItems.length === 0) {
				ctx.ui.notify("No todos. Create a plan first with /plan", "info");
				return;
			}
			const list = todoItems.map((item, i) => `${i + 1}. ${item.completed ? "✓" : "○"} ${item.text}`).join("\n");
			ctx.ui.notify(`Plan Progress:\n${list}`, "info");
		},
	});

	pi.registerShortcut(Key.ctrlAlt("p"), {
		description: "Toggle plan mode",
		handler: async (ctx) => togglePlanMode(ctx),
	});

	// Shift+Tab flips between planning and executing. Pi reserves Shift+Tab for
	// app.thinking.cycle, so ~/.pi/agent/keybindings.json must move that binding
	// (pi/keybindings.json does it, linked by setup-dev-env.sh). Otherwise Pi
	// skips this shortcut with a conflict warning.
	pi.registerShortcut("shift+tab", {
		description: "Switch plan mode <-> execute mode",
		handler: async (ctx) => {
			if (executionMode) {
				enterPlanMode(ctx);
				ctx.ui.notify("⏸ Plan mode (read-only). Shift+Tab to execute again.");
				return;
			}

			if (!planModeEnabled) {
				enterPlanMode(ctx);
				ctx.ui.notify("⏸ Plan mode (read-only). Shift+Tab to review the plan.");
				return;
			}

			if (todoItems.length === 0) {
				// Nothing to approve yet: Shift+Tab leaves plan mode instead of
				// pretending to execute an empty plan.
				planModeEnabled = false;
				restoreNormalModeTools();
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

	// Block destructive bash commands in plan mode. Execute mode never reaches
	// this branch: it deliberately has full access to every command.
	pi.on("tool_call", async (event) => {
		if (!planModeEnabled || executionMode || event.toolName !== "bash") return;

		const command = event.input.command as string;
		if (!isSafeCommand(command)) {
			return {
				block: true,
				reason: `Plan mode: command blocked (not allowlisted). Use /plan to disable plan mode first.\nCommand: ${command}`,
			};
		}
	});

	// Filter out stale plan mode context when not in plan mode
	pi.on("context", async (event) => {
		if (planModeEnabled) return;

		return {
			messages: event.messages.filter((m) => {
				const msg = m as AgentMessage & { customType?: string };
				if (msg.customType === "plan-mode-context") return false;
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
	pi.on("before_agent_start", async (event) => {
		if (event.messageType !== "user") return;

		if (planModeEnabled) {
			return {
				message: {
					customType: "plan-mode-context",
					content: `[PLAN MODE ACTIVE]
You are in plan mode - a read-only exploration mode for safe code analysis.

Restrictions:
- Built-in edit and write tools are disabled
- Other currently active tools remain available
- Bash is restricted to an allowlist of read-only commands

Ask clarifying questions when the request is ambiguous.

Create a detailed numbered plan under a "Plan:" header:

Plan:
1. First step description
2. Second step description
...

Do NOT attempt to make changes - just describe what you would do. Then stop and
wait: the user approves, keeps planning, or asks for a revision, and every
revised plan is presented for approval again.`,
					display: false,
				},
			};
		}

		if (executionMode && todoItems.length > 0) {
			const remaining = todoItems.filter((t) => !t.completed);
			const todoList = remaining.map((t) => `${t.step}. ${t.text}`).join("\n");
			return {
				message: {
					customType: "plan-execution-context",
					content: `[EXECUTING PLAN - Full tool access enabled]

Remaining steps:
${todoList}

Execute each step in order.
Every tool and every bash command is available; nothing is restricted in execute mode.
After completing each step, call the plan_done tool with that step's number immediately (e.g. {"steps":[1]}), and also include a [DONE:n] tag in your text as a backup.`,
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
			// Fallback: the model wrapped up without [DONE:n] tags ("All steps complete").
			const lastAssistant = [...event.messages].reverse().find(isAssistantMessage);
			if (lastAssistant && allStepsComplete(getTextContent(lastAssistant))) {
				for (const t of todoItems) t.completed = true;
			}
			if (todoItems.every((t) => t.completed)) {
				const completedList = todoItems.map((t) => `~~${t.text}~~`).join("\n");
				pi.sendMessage(
					{ customType: "plan-complete", content: `**Plan Complete!** ✓\n\n${completedList}`, display: true },
					// nextTurn: delivered with the next user prompt instead of triggering an
					// extra (expensive, reasoning-max) LLM turn to acknowledge the card.
					{ deliverAs: "nextTurn" },
				);
				executionMode = false;
				todoItems = [];
				updateStatus(ctx);
				persistState(); // Save cleared state so resume doesn't restore old execution mode
			}
			return;
		}

		if (!planModeEnabled || !ctx.hasUI) return;

		// Extract todos from last assistant message
		const lastAssistant = [...event.messages].reverse().find(isAssistantMessage);
		if (lastAssistant) {
			const extracted = extractTodoItems(getTextContent(lastAssistant));
			if (extracted.length > 0) {
				todoItems = extracted;
			}
		}

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
			toolsBeforePlanMode = planModeEntry.data.toolsBeforePlanMode ?? toolsBeforePlanMode;
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

		if (planModeEnabled) {
			enablePlanModeTools();
		}
		updateStatus(ctx);
	});
}
