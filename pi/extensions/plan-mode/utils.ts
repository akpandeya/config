/**
 * Pure utility functions for plan mode.
 * Extracted for testability.
 *
 * Vendored from examples/extensions/plan-mode/utils.ts in
 * @earendil-works/pi-coding-agent 1.5.2 — see pi/README.md.
 */

// Destructive commands blocked in plan mode
const DESTRUCTIVE_PATTERNS = [
	/\brm\b/i,
	/\brmdir\b/i,
	/\bmv\b/i,
	/\bcp\b/i,
	/\bmkdir\b/i,
	/\btouch\b/i,
	/\bchmod\b/i,
	/\bchown\b/i,
	/\bchgrp\b/i,
	/\bln\b/i,
	/\btee\b/i,
	/\btruncate\b/i,
	/\bdd\b/i,
	/\bshred\b/i,
	/(^|[^<])>(?!>)/,
	/>>/,
	/\bnpm\s+(install|uninstall|update|ci|link|publish)/i,
	/\byarn\s+(add|remove|install|publish)/i,
	/\bpnpm\s+(add|remove|install|publish)/i,
	/\bpip\s+(install|uninstall)/i,
	/\bapt(-get)?\s+(install|remove|purge|update|upgrade)/i,
	/\bbrew\s+(install|uninstall|upgrade)/i,
	/\bgit\s+(add|commit|push|pull|merge|rebase|reset|checkout|branch\s+-[dD]|stash|cherry-pick|revert|tag|init|clone)/i,
	/\bsudo\b/i,
	/\bsu\b/i,
	/\bkill\b/i,
	/\bpkill\b/i,
	/\bkillall\b/i,
	/\breboot\b/i,
	/\bshutdown\b/i,
	/\bsystemctl\s+(start|stop|restart|enable|disable)/i,
	/\bservice\s+\S+\s+(start|stop|restart)/i,
	/\b(vim?|nano|emacs|code|subl)\b/i,
];

// Safe read-only commands allowed in plan mode
const SAFE_PATTERNS = [
	/^\s*cat\b/,
	/^\s*head\b/,
	/^\s*tail\b/,
	/^\s*less\b/,
	/^\s*more\b/,
	/^\s*grep\b/,
	/^\s*find\b/,
	/^\s*ls\b/,
	/^\s*pwd\b/,
	/^\s*echo\b/,
	/^\s*printf\b/,
	/^\s*wc\b/,
	/^\s*sort\b/,
	/^\s*uniq\b/,
	/^\s*diff\b/,
	/^\s*file\b/,
	/^\s*stat\b/,
	/^\s*du\b/,
	/^\s*df\b/,
	/^\s*tree\b/,
	/^\s*which\b/,
	/^\s*whereis\b/,
	/^\s*type\b/,
	/^\s*env\b/,
	/^\s*printenv\b/,
	/^\s*uname\b/,
	/^\s*whoami\b/,
	/^\s*id\b/,
	/^\s*date\b/,
	/^\s*cal\b/,
	/^\s*uptime\b/,
	/^\s*ps\b/,
	/^\s*top\b/,
	/^\s*htop\b/,
	/^\s*free\b/,
	/^\s*git\s+(status|log|diff|show|branch|remote|config\s+--get)/i,
	/^\s*git\s+ls-/i,
	/^\s*npm\s+(list|ls|view|info|search|outdated|audit)/i,
	/^\s*yarn\s+(list|info|why|audit)/i,
	/^\s*node\s+--version/i,
	/^\s*python\s+--version/i,
	/^\s*curl\s/i,
	/^\s*wget\s+-O\s*-/i,
	// Jira CLI read-only lookups (view/list/board/sprint/comment list).
	// Positive allowlist: create/edit/move/etc. never match and stay blocked.
	/^\s*jira\s+(view|list|issue\s+view|issue\s+list|board|sprint|comment\s+list)\b/,
	/^\s*jq\b/,
	/^\s*sed\s+-n/i,
	/^\s*awk\b/,
	/^\s*rg\b/,
	/^\s*fd\b/,
	/^\s*bat\b/,
	/^\s*eza\b/,
];

export function isSafeCommand(command: string): boolean {
	const isDestructive = DESTRUCTIVE_PATTERNS.some((p) => p.test(command));
	const isSafe = SAFE_PATTERNS.some((p) => p.test(command));
	return !isDestructive && isSafe;
}

export interface TodoItem {
	step: number;
	text: string;
	completed: boolean;
}

export function cleanStepText(text: string): string {
	let cleaned = text
		.replace(/\*{1,2}([^*]+)\*{1,2}/g, "$1") // Remove bold/italic
		.replace(/`([^`]+)`/g, "$1") // Remove code
		.replace(
			/^(Use|Run|Execute|Create|Write|Read|Check|Verify|Update|Modify|Add|Remove|Delete|Install)\s+(the\s+)?/i,
			"",
		)
		.replace(/\s+/g, " ")
		.trim();

	if (cleaned.length > 0) {
		cleaned = cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
	}
	// Keep full text: the exec message and the widget both need the whole step.
	// todos-view.ts wraps it into the available columns (never pre-truncated here).
	return cleaned;
}

/**
 * Drop fenced code regions (``` / ~~~, indented variants included, unclosed
 * fences run to end of message). A plan *shown* inside a fence is an
 * illustration — a diff, a doc snippet, a test prompt — not the agent's own
 * plan. Matching one armed the approval dialog with a step list that was never
 * proposed for execution (observed: a 23-step test fixture in a reply became
 * the session's todo list).
 */
export function stripFencedCode(text: string): string {
	const kept: string[] = [];
	let fence: string | undefined;
	for (const line of text.split("\n")) {
		const match = line.trimStart().match(/^(`{3,}|~{3,})/);
		if (fence === undefined) {
			if (match) {
				fence = match[1];
				continue;
			}
			kept.push(line);
		} else if (match && match[1][0] === fence[0] && match[1].length >= fence.length) {
			fence = undefined;
		}
	}
	return kept.join("\n");
}

export function extractTodoItems(message: string): TodoItem[] {
	const items: TodoItem[] = [];
	// Ignore plans quoted inside fenced code (see stripFencedCode).
	const scannable = stripFencedCode(message);
	// Take the LAST "Plan:" section: since getTextContent includes thinking blocks,
	// a draft in the reasoning block can precede the user-visible plan in the text
	// block — the text block comes last in content order.
	// Header must sit on a line of its own (start-of-line, optional "#"/bold
	// markers, nothing else on the line). The old mid-sentence pattern
	// (\*{0,2}Plan:\*{0,2}\s*\n) also matched prose like "…present the plan:**",
	// which scraped unrelated numbered lists (e.g. clarifying questions) as
	// plan steps and fired the approval dialog on non-plans.
	const headers = [...scannable.matchAll(/^\s*(?:#{1,6}\s+)?\*{0,2}Plan:?\*{0,2}\s*$/gim)];
	if (headers.length === 0) return items;
	const lastHeader = headers[headers.length - 1];
	const planSection = scannable.slice((lastHeader.index ?? 0) + lastHeader[0].length);
	// Full-line capture: step titles may contain bold/italic/backticks ("1. **Step** \`x\` …").
	// cleanStepText strips the markdown; / and - items are still skipped below.
	const numberedPattern = /^\s*(\d+)[.)]\s+(.+)$/gm;

	for (const match of planSection.matchAll(numberedPattern)) {
		const text = match[2]
			.trim()
			.replace(/\*{1,2}$/, "")
			.trim();
		if (text.length > 5 && !text.startsWith("/") && !text.startsWith("-")) {
			const cleaned = cleanStepText(text);
			if (cleaned.length > 3) {
				items.push({ step: items.length + 1, text: cleaned, completed: false });
			}
		}
	}
	return items;
}

/**
 * Block-aware plan extraction. `blocks` are the assistant message's content
 * blocks in order (thinking first, visible text last). Only the LAST block
 * containing a "Plan:" header is scanned, and only within that block.
 *
 * Why not just join the blocks and take the last header: when the visible text
 * had no header (e.g. it said "Revised plan:" mid-sentence) but a thinking
 * draft did, the slice leaked past the header's block into every later block,
 * merging the thinking draft's steps with the final plan's steps into one
 * phantom list (observed live: a 10-step dialog built from 5 + 5).
 */
export function extractTodoItemsFromBlocks(blocks: string[]): TodoItem[] {
	const headerRe = /^\s*(?:#{1,6}\s+)?\*{0,2}Plan:?\*{0,2}\s*$/im;
	for (let i = blocks.length - 1; i >= 0; i--) {
		if (headerRe.test(stripFencedCode(blocks[i]))) {
			return extractTodoItems(blocks[i]);
		}
	}
	return [];
}

export function extractDoneSteps(message: string): number[] {
	const steps: number[] = [];
	// Canonical and bracket variants: [DONE:1], [DONE: 1], [DONE 1], [Done:1]
	for (const match of message.matchAll(/\[DONE\s*:?\s*(\d+)\]/gi)) {
		steps.push(Number(match[1]));
	}
	// "Done: 1" without brackets
	for (const match of message.matchAll(/\bDone\s*:\s*(\d+)\b/gi)) {
		steps.push(Number(match[1]));
	}
	// "Step 1 done", "Step 2 is complete", "Step 3 finished" — adjacency-anchored,
	// so "Step 9 is not done" / "Step 9 incomplete" never match.
	for (const match of message.matchAll(/\bStep\s*(\d+)\s+(?:is\s+)?(?:done|complete|completed|finished)\b/gi)) {
		steps.push(Number(match[1]));
	}
	return [...new Set(steps)];
}

export function markCompletedSteps(text: string, items: TodoItem[]): number {
	const doneSteps = extractDoneSteps(text);
	let marked = 0;
	for (const step of doneSteps) {
		const item = items.find((t) => t.step === step && !t.completed);
		if (item) {
			item.completed = true;
			marked++;
		}
	}
	return marked;
}

// Whole-plan completion phrasing, used as a fallback when the model summarizes
// without [DONE:n] tags. Only consulted on the run's final message (agent_end).
export function allStepsComplete(message: string): boolean {
	return (
		/(?:all|every)\s+steps?\s+(?:are|is\s+)?(?:done|complete|completed|finished)/i.test(message) ||
		/\b(?:the\s+)?plan\s+(?:is\s+)?(?:complete|completed|done)\b/i.test(message)
	);
}

export interface ImplementerPick {
	/** Model id or name the planner named for implementation. */
	pick: string;
	/** Short reason after the dash; empty when the planner omitted it. */
	reason: string;
	/** Planner asked to skip the first review pass (`; review: skip` on the line). */
	reviewSkip: boolean;
}

/**
 * The planner ends its plan with one unnumbered line naming an implementer:
 *
 *   Implementer: Claude Sonnet 5.5 — cross-cutting auth changes
 *
 * The planner may also request skipping the first review pass by appending
 * `; review: skip` (for trivial, mechanical, or debug-only changes):
 *
 *   Implementer: glm-5.3-flash — mechanical symlink fix; review: skip
 *
 * Fenced examples are ignored (the plan itself may show the line in a code
 * block), and the last match wins so a revised plan can change its pick.
 */
export function extractImplementerPick(blocks: string[]): ImplementerPick | undefined {
	for (let i = blocks.length - 1; i >= 0; i--) {
		const scannable = stripFencedCode(blocks[i]);
		const matches = [...scannable.matchAll(/^[ \t]*Implementer:[ \t]*(.+)$/gim)];
		const match = matches.at(-1);
		if (!match) continue;

		// Strip emphasis/code markers, then split on a spaced dash (em/en) or a
		// colon. Model names contain hyphens without spaces ("GPT-6 Luna"), so
		// they stay intact.
		const raw = match[1].replace(/[`*]/g, "").trim();
		if (!raw) continue;
		const split =
			raw.match(/^(.*?)\s+[—–]\s+(.*)$/) ?? raw.match(/^(.*?):\s+(.*)$/) ?? raw.match(/^(.*?)\s+-\s+(.*)$/);
		const pick = (split?.[1] ?? raw).trim();
		const reason = (split?.[2] ?? "").trim();
		// Not followed by a word char or hyphen, so "review: skip-tuning" is not
		// a skip request.
		if (pick) return { pick, reason, reviewSkip: /\breview:\s*skip(?:ped)?\b(?![\w-])/i.test(raw) };
	}
	return undefined;
}

export interface ReviewerPick {
	/** Model id or name the planner named for review. */
	pick: string;
	/** Short reason after the dash, with the rounds clause removed. */
	reason: string;
	/** `; rounds: n` on the line — how many review rounds the planner suggests. */
	rounds?: number;
}

/**
 * The planner may add one unnumbered line after the plan naming a reviewer and
 * an optional review-round budget:
 *
 *   Reviewer: Kimi K3.1 Pro — deep review; rounds: 3
 *
 * Fenced examples are ignored (the plan itself may show the line in a code
 * block), and the last match wins so a revised plan can change its pick.
 */
export function extractReviewerPick(blocks: string[]): ReviewerPick | undefined {
	for (let i = blocks.length - 1; i >= 0; i--) {
		const scannable = stripFencedCode(blocks[i]);
		const matches = [...scannable.matchAll(/^[ \t]*Reviewer:[ \t]*(.+)$/gim)];
		const match = matches.at(-1);
		if (!match) continue;

		const raw = match[1].replace(/[`*]/g, "").trim();
		if (!raw) continue;
		const roundsMatch = raw.match(/\brounds?:\s*(\d+)\b/i);
		const rounds = roundsMatch ? Number(roundsMatch[1]) : undefined;
		const withoutRounds = raw.replace(/[;,]?\s*\brounds?:\s*\d+\b/i, "").trim();
		// Same dash/colon split as extractImplementerPick: model names contain
		// hyphens without spaces, so they stay intact.
		const split =
			withoutRounds.match(/^(.*?)\s+[—–]\s+(.*)$/) ??
			withoutRounds.match(/^(.*?):\s+(.*)$/) ??
			withoutRounds.match(/^(.*?)\s+-\s+(.*)$/);
		const pick = (split?.[1] ?? withoutRounds).trim();
		const reason = (split?.[2] ?? "").trim();
		if (pick) return { pick, reason, rounds };
	}
	return undefined;
}

interface ModelChoiceCandidate {
	model: { id: string; name: string };
}

/**
 * Resolve a loose model mention to one of the candidates: exact id/name first,
 * then a prefix in either direction, preferring the longest match so
 * "Kimi K3" cannot win over "Kimi K3.1 Pro" when both are offered.
 */
export function matchModelChoice<T extends ModelChoiceCandidate>(
	pick: string,
	candidates: readonly T[],
): T | undefined {
	const normalized = pick.trim().toLowerCase().replace(/[`*]/g, "");
	if (!normalized) return undefined;

	let best: { candidate: T; score: number; length: number } | undefined;
	for (const candidate of candidates) {
		const id = candidate.model.id.toLowerCase();
		const name = candidate.model.name.toLowerCase();
		let score = -1;
		if (id === normalized || name === normalized) score = 0;
		else if (id.startsWith(normalized) || name.startsWith(normalized)) score = 1;
		else if (normalized.startsWith(id) || normalized.startsWith(name)) score = 2;
		if (score === -1) continue;

		const length = Math.max(id.length, name.length);
		if (!best || score < best.score || (score === best.score && length > best.length)) {
			best = { candidate, score, length };
		}
	}
	return best?.candidate;
}

export interface ReviewVerdict {
	approved: boolean;
	/** `CHANGES NEEDED` findings; empty on approval. */
	findings: string[];
}

/**
 * The reviewer ends its turn with `Verdict: APPROVED` or
 * `Verdict: CHANGES NEEDED` followed by bullet findings. Fenced examples are
 * ignored, the last verdict wins, and findings fall back to the whole block
 * when the reviewer puts the verdict line last.
 */
export function extractReviewVerdict(blocks: string[]): ReviewVerdict | undefined {
	for (let i = blocks.length - 1; i >= 0; i--) {
		const text = stripFencedCode(blocks[i]);
		const matches = [
			...text.matchAll(
				/^[ \t]*(?:#{1,6}[ \t]*)?\*{0,2}[ \t]*Verdict:[ \t]*\*{0,2}[ \t]*(APPROVED|CHANGES[ \t]+NEEDED)[ \t]*\*{0,2}[ \t]*$/gim,
			),
		];
		const match = matches.at(-1);
		if (!match) continue;

		// A qualified verdict ("Verdict: APPROVED, but ...") is not an approval:
		// the end anchor above makes it a malformed verdict, which callers treat
		// as no verdict rather than silently approving.
		const approved = match[1].toUpperCase() === "APPROVED";
		const previous = matches.at(-2);
		const sectionStart = previous ? (previous.index ?? 0) + previous[0].length : 0;
		const beforeVerdict = text.slice(sectionStart, match.index ?? 0);
		const after = text.slice((match.index ?? 0) + match[0].length);
		const bullets = (chunk: string): string[] =>
			chunk
				.split("\n")
				.map((line) => line.match(/^\s*(?:[-*+]|\d+[.)])\s+(.+)$/)?.[1]?.replace(/[`*]/g, "").trim())
				.filter((line): line is string => Boolean(line));

		let findings = approved ? [] : bullets(after);
		// Fall back only within this verdict's own section, so bullets from an
		// earlier (already resolved) verdict are not resurrected as findings.
		if (!approved && findings.length === 0) findings = bullets(beforeVerdict);
		if (!approved && findings.length === 0) {
			const prose = beforeVerdict.trim();
			if (prose) findings = [prose.slice(0, 4000)];
		}
		return { approved, findings };
	}
	return undefined;
}
