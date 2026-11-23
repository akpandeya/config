/**
 * Steering Frame - framed delivery for mid-run steering messages.
 *
 * Inspiration: the pi-cc-steer package (Claude Code-style mid-turn steering),
 * reimplemented locally as a thin layer over pi's native queueing.
 *
 * What pi already does: with `steeringMode: "all"`, messages typed while the
 * agent is running are queued and delivered together after the current turn's
 * tool calls, before the next LLM call. This extension adds only the framing:
 * at the next LLM call, the batch of steered user messages is folded into a
 * single framed block telling the model these are mid-task course corrections.
 *
 * Scope is deliberately request-only: the session transcript keeps the raw
 * user messages, so history, export and display are untouched. Only what the
 * model sees changes (via the `context_with_system` hook).
 *
 * Correlation model (how recorded inputs meet delivered messages):
 *
 * - `input` (streamingBehavior "steer") records `{ text, hasImages }` in
 *   arrival order. Text is raw, before skill/template expansion.
 * - `message_end` for a user message that arrives after the run's first
 *   assistant message is a native queue delivery (the run's own prompt fires
 *   before any assistant message and is excluded). Deliveries are FIFO, so:
 *   a delivery that prefix-matches a pending record binds to it (the record's
 *   text is updated to the final delivered text); a delivery that matches
 *   nothing retires the oldest pending record — its delivery window has
 *   passed, and leaving it armed could falsely frame a later follow-up.
 *   Expanded skill/template steers therefore deliver unframed (benign).
 * - `context_with_system` walks the transcript tail backwards, matching user
 *   messages against pending records plus `framed` records (see retry below),
 *   and folds the matched run into one framed user message.
 * - Matched records move to `framed` and stay there until `turn_end` reports
 *   `outcome: "completed"`. If pi retries the request after a retryable error,
 *   the retry's `context_with_system` re-frames the same batch instead of
 *   sending it raw. Settle and session start clear everything.
 *
 * Not implemented (on purpose): queue editing (↑). Pi's extension API does not
 * expose queue manipulation, so editing would require the extension to own the
 * whole queue, including abort behavior and skill/template expansion.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { AgentMessage } from "@earendil-works/pi-agent-core";

interface SteerRecord {
	/** Recorded text; for bound records, the final delivered text. */
	text: string;
	/** Whether the steered input carried images. */
	hasImages: boolean;
}

function messageText(message: AgentMessage): string {
	if (message.role !== "user") return "";
	const content = message.content;
	if (typeof content === "string") return content;
	return content
		.filter((block) => block.type === "text")
		.map((block) => block.text)
		.join("\n");
}

function messageImages(message: AgentMessage) {
	if (message.role !== "user") return [];
	const content = message.content;
	if (typeof content === "string") return [];
	return content.filter((block) => block.type === "image");
}

/**
 * Does a delivered transcript message correspond to a steer record? Text is
 * compared as a trimmed prefix in either direction-safe form; skill/template
 * expansion can change the text, which is why unmatchable deliveries retire
 * the oldest record instead of sticking around. An image-only record matches
 * a delivered message that has images and no text.
 */
function matchesRecord(deliveredMessage: AgentMessage, record: SteerRecord): boolean {
	const text = messageText(deliveredMessage);
	const hasImages = messageImages(deliveredMessage).length > 0;
	const rawTrimmed = record.text.trim();
	if (rawTrimmed.length === 0) {
		return record.hasImages && hasImages && text.trim().length === 0;
	}
	if (text.trim().length === 0) return false;
	const deliveredTrimmed = text.trimStart();
	return (
		deliveredTrimmed.startsWith(rawTrimmed) ||
		deliveredTrimmed.startsWith(rawTrimmed.replace(/\s+/g, " "))
	);
}

function buildFrame(messages: AgentMessage[]): string {
	const lines: string[] = [];
	const count = messages.length;
	lines.push("<user-steering>");
	lines.push(
		`The following ${count} message${count === 1 ? "" : "s"} arrived from the user while you were working. Treat them as mid-task course corrections:`,
	);
	lines.push("- Address each message before continuing.");
	lines.push("- Adjust your plan or approach if the messages require it.");
	lines.push("- Continue the current task unless a message says otherwise.");
	lines.push("");
	lines.push("Messages:");
	messages.forEach((message, i) => {
		const text = messageText(message).trim();
		const body = text.length > 0 ? text.split("\n") : ["(image attachment, no text)"];
		body.forEach((line, j) => {
			lines.push(j === 0 ? `${i + 1}. ${line}` : `   ${line}`);
		});
	});
	lines.push("</user-steering>");
	return lines.join("\n");
}

export default function steeringFrameExtension(pi: ExtensionAPI): void {
	/** Steered inputs awaiting native delivery, in arrival order. */
	let pending: SteerRecord[] = [];
	/**
	 * Records already folded into a frame on the current request, kept until
	 * the turn completes so an automatic retry re-frames the same batch.
	 */
	let framed: SteerRecord[] = [];
	/** Whether the current run has produced an assistant message yet. */
	let runSawAssistant = false;

	function updateStatus(ctx: ExtensionContext): void {
		if (pending.length > 0) {
			ctx.ui.setStatus(
				"steer-frame",
				ctx.ui.theme.fg("accent", `⇡ ${pending.length} steered`),
			);
		} else {
			ctx.ui.setStatus("steer-frame", undefined);
		}
	}

	pi.on("input", async (event, ctx) => {
		if (event.streamingBehavior !== "steer") return;
		const hasImages = (event.images?.length ?? 0) > 0;
		const text = event.text;
		if (text.trim().length === 0 && !hasImages) return;
		pending.push({ text, hasImages });
		updateStatus(ctx);
	});

	// Race guard: a steer typed while a run is starting can be consumed as that
	// run's prompt instead of queued. If the run prompt is exactly one of the
	// recorded steers, drop it so it is not framed later. Exact match on
	// purpose: prefix matching could drop a different, prefix-related pending
	// entry; a missed drop only stays pending until agent_settled clears it.
	pi.on("before_agent_start", async (event, ctx) => {
		if (event.messageType !== "user" || pending.length === 0) return;
		const prompt = event.prompt.trim();
		const idx = pending.findIndex((p) => p.text.trim() === prompt);
		if (idx >= 0) {
			pending.splice(idx, 1);
			updateStatus(ctx);
		}
	});

	pi.on("agent_start", async () => {
		runSawAssistant = false;
	});

	pi.on("message_end", async (event) => {
		const message = event.message;
		if (message.role === "assistant") {
			runSawAssistant = true;
			return;
		}
		// Correlate native queue deliveries (user messages appended after the
		// run's first assistant message) with pending records.
		if (message.role !== "user" || !runSawAssistant || pending.length === 0) return;

		const boundIdx = pending.findLastIndex((record) => matchesRecord(message, record));
		if (boundIdx >= 0) {
			// Bind: remember the final delivered text so the context-time match
			// is exact even when skill/template expansion changed the wording.
			const record = pending[boundIdx];
			record.text = messageText(message);
			record.hasImages = messageImages(message).length > 0 || record.hasImages;
			return;
		}
		// FIFO: this delivery just arrived, so every older pending record was
		// delivered before it and missed its framing window. Retire the oldest
		// one (typically a skill/template-expanded steer). If the delivery
		// actually belonged to another extension's injected message, retiring
		// one record is still the benign direction: a later delivery then goes
		// out unframed rather than a follow-up being falsely framed.
		pending.shift();
	});

	pi.on("context_with_system", async (event, ctx) => {
		if (pending.length === 0 && framed.length === 0) return;
		const messages = event.messages;

		// Walk backwards from the end. Each trailing user message is matched
		// against the newest unconsumed record: pending records first (they
		// are newer), then framed records. A steer queued while the batch was
		// being prepared stays pending untouched, because the tail simply runs
		// out of matching messages before reaching it.
		const pool = [...pending];
		let matchedCount = 0;
		while (matchedCount < messages.length && pool.length + framed.length > 0) {
			const message = messages[messages.length - 1 - matchedCount];
			if (message.role !== "user") break;

			let poolIdx = pool.findLastIndex((record) => matchesRecord(message, record));
			if (poolIdx >= 0) {
				// Consumed into the current frame; keep a copy in `framed` for
				// retry safety.
				framed.push(...pool.splice(poolIdx, 1));
			} else {
				const framedIdx = framed.findLastIndex((record) => matchesRecord(message, record));
				if (framedIdx < 0) break;
			}
			matchedCount++;
		}
		if (matchedCount === 0) return;

		// Retirement of delivered-but-unmatched records is handled by the
		// message_end correlation above (FIFO: an unmatched delivery retires
		// the oldest pending record), so nothing extra is needed here.

		const start = messages.length - matchedCount;
		const batch = messages.slice(start);
		const images = batch.flatMap((m) => messageImages(m));
		const frame = buildFrame(batch);

		const framedMessage: AgentMessage =
			images.length === 0
				? { role: "user", content: frame, timestamp: Date.now() }
				: {
						role: "user",
						content: [{ type: "text", text: frame }, ...images],
						timestamp: Date.now(),
					};

		const next = [...messages.slice(0, start), framedMessage];
		updateStatus(ctx);
		return { messages: next };
	});

	// A completed turn proves the framed request reached the model; drop its
	// records. Non-completed outcomes keep them so an automatic retry (which
	// re-invokes context_with_system with the same tail) re-frames the batch.
	pi.on("turn_end", async (event) => {
		if (event.outcome === "completed" && framed.length > 0) {
			framed = [];
		}
	});

	// Abort returns queued messages to the editor natively; stale records must
	// never frame an unrelated future prompt. Settled also covers the normal
	// end of a run, clearing any leftovers.
	pi.on("agent_settled", async (_event, ctx) => {
		if (pending.length === 0 && framed.length === 0) return;
		pending = [];
		framed = [];
		updateStatus(ctx);
	});

	pi.on("session_start", async (_event, ctx) => {
		pending = [];
		framed = [];
		runSawAssistant = false;
		updateStatus(ctx);
	});
}
