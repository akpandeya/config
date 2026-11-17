/**
 * Background Pre-Compaction Extension
 *
 * Pre-computes a compaction summary in the background once the context crosses
 * a threshold (default 200k tokens), so that when compaction actually runs it
 * is instant instead of blocking the run for a long summarization call.
 *
 * Behavior:
 * - turn_end: when context tokens >= PRECOMPUTE_THRESHOLD and no valid cached
 *   summary exists, start a background summarization (never awaited, never
 *   blocks the run). Shown only as a footer status line.
 * - agent_end: when a summary is ready and tokens are still past the threshold,
 *   propose "compact now?" with a timeout. Declining is remembered until the
 *   next summary; the run is never interrupted mid-turn.
 * - session_before_compact (manual/threshold): if the cached summary's cut
 *   point is still valid, return it so compaction completes instantly.
 *   Overflow recovery falls through to default compaction.
 * - Invalidation: /tree, /fork, session switch, compaction completion/failure,
 *   or the cut point no longer being on the branch.
 *
 * Validity trick: the cut keeps the last KEEP_MARGIN tokens (60k) rather than
 * Pi's keepRecentTokens (20k). Since the context only grows, Pi's later cut is
 * always at-or-after this cut, so the cached summary always covers a superset
 * of what Pi would summarize — redundant but correct, and it stays reusable as
 * new messages arrive.
 *
 * Summary model: opencode-go/glm-5.3-flash (cheap, fast). Fallback: active model.
 */

import { uuidv7 } from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { convertToLlm, serializeConversation } from "@earendil-works/pi-coding-agent";

const PRECOMPUTE_THRESHOLD = 200_000; // tokens; start background summarization here
const KEEP_MARGIN = 60_000; // tokens kept verbatim below the cut (>= Pi's keepRecentTokens)
const SUMMARY_MODEL_PROVIDER = "opencode-go";
const SUMMARY_MODEL_ID = "glm-5.3-flash";
const PROPOSAL_TIMEOUT_MS = 30_000;

interface CachedSummary {
	summary: string;
	firstKeptEntryId: string;
	computedAtTokens: number;
}

export default function backgroundCompactionExtension(pi: ExtensionAPI): void {
	let cache: CachedSummary | undefined;
	let inflight: AbortController | undefined;
	let proposedFor: string | undefined; // firstKeptEntryId we already asked about

	function setStatus(ctx: ExtensionContext, text: string | undefined): void {
		ctx.ui.setStatus("bg-compaction", text ? ctx.ui.theme.fg("muted", text) : undefined);
	}

	function invalidate(): void {
		inflight?.abort();
		inflight = undefined;
		cache = undefined;
		proposedFor = undefined;
	}

	function tokensOf(entry: unknown): number {
		// Cheap estimate: ~4 chars per token over the serialized message content.
		try {
			return Math.ceil(JSON.stringify(entry).length / 4) + 8;
		} catch {
			return 0;
		}
	}

	/**
	 * Compute the cut point over the projected context: walk backwards from the
	 * end accumulating estimates until KEEP_MARGIN is covered, then snap forward
	 * to the user message that starts that span (user-message boundary).
	 * Returns { firstKeptEntryId, messagesToSummarize } or undefined when the
	 * context is too small / has no usable boundary.
	 */
	function computeCut(ctx: ExtensionContext): { firstKeptEntryId: string; messagesToSummarize: unknown[] } | undefined {
		const entries = ctx.sessionManager.buildContextEntries() as unknown as Array<Record<string, unknown>>;
		const messageEntries = entries.filter((e) => e.type === "message" && e.message);
		if (messageEntries.length < 2) return undefined;

		let acc = 0;
		let cutIndex = -1; // index of the first kept entry
		for (let i = messageEntries.length - 1; i >= 0; i--) {
			acc += tokensOf(messageEntries[i]);
			if (acc >= KEEP_MARGIN) {
				cutIndex = i;
				break;
			}
		}
		if (cutIndex <= 0) return undefined; // everything fits in the margin

		// Snap to a user-message boundary: the first kept entry must start a span.
		while (cutIndex < messageEntries.length) {
			const msg = (messageEntries[cutIndex] as { message: { role: string } }).message;
			if (msg.role === "user") break;
			cutIndex++;
		}
		if (cutIndex >= messageEntries.length) return undefined;

		return {
			firstKeptEntryId: String(messageEntries[cutIndex].id),
			messagesToSummarize: messageEntries
				.slice(0, cutIndex)
				.map((e) => (e as { message: unknown }).message),
		};
	}

	async function precompute(ctx: ExtensionContext): Promise<void> {
		const controller = new AbortController();
		inflight = controller;
		setStatus(ctx, "⏳ pre-compaction summary…");
		try {
			const cut = computeCut(ctx);
			if (!cut) {
				setStatus(ctx, undefined);
				return;
			}

			const model =
				ctx.modelRegistry.find(SUMMARY_MODEL_PROVIDER, SUMMARY_MODEL_ID) ?? ctx.model;
			if (!model) {
				setStatus(ctx, undefined);
				return;
			}

			const conversationText = serializeConversation(
				convertToLlm(cut.messagesToSummarize as Parameters<typeof convertToLlm>[0]),
			);
			const summaryMessages = [
				{
					role: "user" as const,
					content: [
						{
							type: "text" as const,
							text: `You are a conversation summarizer. Create a comprehensive summary of this conversation that captures:

1. The main goals and objectives discussed
2. Key decisions made and their rationale
3. Important code changes, file modifications, or technical details
4. Current state of any ongoing work
5. Any blockers, issues, or open questions
6. Next steps that were planned or suggested

Be thorough but concise. The summary will replace this portion of the conversation history, so include all information needed to continue the work effectively. Recent messages near the end are kept verbatim separately; focus on everything up to and including the last completed exchange.

Format the summary as structured markdown with clear sections.

<conversation>
${conversationText}
</conversation>`,
						},
					],
					timestamp: Date.now(),
				},
			];

			const response = await ctx.modelRegistry.complete(
				model,
				{ messages: summaryMessages as never },
				{ maxTokens: 8192, signal: controller.signal, cacheRetention: "none", sessionId: uuidv7() },
			);
			if (controller.signal.aborted) return;

			const summary = response.content
				.filter((c): c is { type: "text"; text: string } => c.type === "text")
				.map((c) => c.text)
				.join("\n");

			if (!summary.trim()) {
				setStatus(ctx, undefined);
				return;
			}

			cache = {
				summary,
				firstKeptEntryId: cut.firstKeptEntryId,
				computedAtTokens: ctx.getContextUsage()?.tokens ?? 0,
			};
			setStatus(ctx, "✓ pre-compaction summary ready");
		} catch (error) {
			if (!controller.signal.aborted) {
				const message = error instanceof Error ? error.message : String(error);
				setStatus(ctx, `pre-compaction summary failed: ${message}`);
			} else {
				setStatus(ctx, undefined);
			}
		} finally {
			if (inflight === controller) inflight = undefined;
		}
	}

	function cutStillOnBranch(ctx: ExtensionContext): boolean {
		if (!cache) return false;
		const branch = ctx.sessionManager.getBranch() as Array<{ id?: string }>;
		return branch.some((e) => e?.id === cache!.firstKeptEntryId);
	}

	pi.on("turn_end", async (event, ctx) => {
		if (event.outcome && event.outcome !== "completed") return;
		const tokens = ctx.getContextUsage()?.tokens;
		if (tokens == null || tokens < PRECOMPUTE_THRESHOLD) return;
		if (cache || inflight) return;
		// Fire and forget — never blocks the run.
		void precompute(ctx);
	});

	pi.on("agent_end", async (_event, ctx) => {
		const tokens = ctx.getContextUsage()?.tokens;
		if (!cache || tokens == null || tokens < PRECOMPUTE_THRESHOLD) return;
		if (proposedFor === cache.firstKeptEntryId) return;
		proposedFor = cache.firstKeptEntryId;
		if (!ctx.hasUI) return;

		const compactNow = await ctx.ui.confirm(
			"Pre-compaction summary ready",
			`Context is at ~${tokens.toLocaleString()} tokens and a summary is already prepared. Compact now?`,
			{ timeout: PROPOSAL_TIMEOUT_MS },
		);
		if (compactNow) {
			setStatus(ctx, undefined);
			ctx.compact({
				onComplete: () => ctx.ui.notify("Compaction completed", "info"),
				onError: (error) => ctx.ui.notify(`Compaction failed: ${error.message}`, "error"),
			});
		}
		// Declined / timed out: keep the summary cached for the natural threshold
		// compaction; don't re-ask until a new summary is computed.
	});

	pi.on("session_before_compact", async (event, ctx) => {
		const { preparation, reason } = event;
		// Overflow recovery needs a cut far enough back to fit the window; our
		// cached summary isn't guaranteed to help, so use default compaction.
		if (reason === "overflow") {
			invalidate();
			return;
		}
		if (!cache || !cutStillOnBranch(ctx)) return;

		const result = {
			compaction: {
				summary: cache.summary,
				firstKeptEntryId: cache.firstKeptEntryId,
				tokensBefore: preparation.tokensBefore,
			},
		};
		cache = undefined;
		proposedFor = undefined;
		inflight?.abort();
		inflight = undefined;
		setStatus(ctx, undefined);
		return result;
	});

	pi.on("session_compact", () => invalidate());
	pi.on("session_compact_failed", () => invalidate());

	pi.on("session_before_tree", () => invalidate());
	pi.on("session_before_fork", () => invalidate());
	pi.on("session_before_switch", () => invalidate());

	pi.on("session_start", async (_event, ctx) => {
		// Fresh runtime: state was captured in module closures of the old runtime.
		cache = undefined;
		inflight = undefined;
		proposedFor = undefined;
		setStatus(ctx, undefined);
	});
}
