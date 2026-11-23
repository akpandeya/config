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
 * - `message_end` for a user message is a native queue delivery, except the
 *   run's own starting prompt. That prompt is identified positionally, not
 *   by text: `before_agent_start` for a user run arms a one-shot guard, and
 *   the first user `message_end` consumes it — while no assistant message
 *   exists yet, that message is the run's own prompt and correlation is
 *   skipped. Text comparison cannot work here because pi builds the starting
 *   message as `prompt + image hints` when images are attached, so the text
 *   never equals the raw prompt. Deliveries usually
 *   arrive after the run's first assistant message, but pi can also drain
 *   queued steers at the very start of a run or automatic continuation,
 *   before any assistant message exists — those correlate too; skipping all
 *   pre-assistant user messages would leave their records armed. Deliveries
 *   are FIFO, so:
 *   a delivery that prefix-matches a pending record binds to it (the record's
 *   text is updated to the final delivered text); a delivery that matches
 *   nothing retires the oldest pending record — its delivery window has
 *   passed, and leaving it armed could falsely frame a later follow-up.
 *   Expanded skill/template steers therefore deliver unframed (benign).
 * - `context_with_system` walks the transcript tail backwards, matching user
 *   messages against pending records plus `framed` records (see retry
 *   below), and folds the matched run into one framed user message. Pending
 *   records consumed by the walk are removed from `pending` (they now live
 *   in `framed`); framed records are consumed from a per-walk copy so one
 *   record cannot match several consecutive user messages, while `framed`
 *   itself keeps them for retry.
 * - Matched records move to `framed` and stay there until `turn_end` reports
 *   `outcome: "completed"` with a non-`length` stop reason. If pi retries the
 *   request after a retryable error — or compacts and retries a response that
 *   hit the length limit, which pi reports as `outcome: "completed"` with
 *   `stopReason: "length"` — the retry's `context_with_system` re-frames the
 *   same batch instead of sending it raw. Settle and session start clear
 *   everything.
 *
 * Known limitation: pi gives deliveries no provenance, so a follow-up that
 * prefix-matches a still-pending steer can bind to it and be framed as
 * steering. Mislabel-only risk: the message still reaches the model.
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
 * any delivered message that carries an image block: pi's queue normalization
 * can append image-hint text to the delivery, and that generated text is not
 * user content, so the delivered text is not required to be empty.
 */
function matchesRecord(deliveredMessage: AgentMessage, record: SteerRecord): boolean {
	const text = messageText(deliveredMessage);
	const hasImages = messageImages(deliveredMessage).length > 0;
	const rawTrimmed = record.text.trim();
	if (rawTrimmed.length === 0) {
		// Image-only record: pi's queue normalization can append hint text to
		// the delivery, so the delivered text is not required to be empty.
		return record.hasImages && hasImages;
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
	/**
	 * One-shot positional guard for the run's own starting prompt: armed by
	 * `before_agent_start` (user runs only), consumed by the first user
	 * `message_end`. While armed and pre-assistant, that first user message is
	 * the run's prompt, not a queue delivery.
	 */
	let promptSkipArmed = false;

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
	// This is also the only place the positional skip guard is armed, so a
	// continuation-only `agent_start` never skips the first user message.
	pi.on("before_agent_start", async (event, ctx) => {
		if (event.messageType !== "user") {
			// Custom-message runs have no user prompt; nothing may be skipped.
			promptSkipArmed = false;
			return;
		}
		promptSkipArmed = true;
		if (pending.length === 0) return;
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

	pi.on("message_end", async (event, ctx) => {
		const message = event.message;
		if (message.role === "assistant") {
			runSawAssistant = true;
			return;
		}
		// Correlate native queue deliveries (user messages appended by the
		// queue drain) with pending records. Pre-assistant user messages are
		// correlated too, because pi can drain queued steers at the very start
		// of a run or automatic continuation — with one exception: the run's
		// own starting prompt, which fires before any assistant message and is
		// not a delivery. That prompt is skipped positionally (one-shot guard,
		// see `promptSkipArmed`), never by text: pi appends image hints to the
		// starting message, so its text differs from the raw prompt.
		if (message.role !== "user" || pending.length === 0) return;
		if (promptSkipArmed) {
			// Consume the guard on the first user message_end either way, so it
			// can never wrongly skip a later delivery.
			promptSkipArmed = false;
			if (!runSawAssistant) return;
		}

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
		// Retirement changed the pending count; refresh the status.
		updateStatus(ctx);
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
		// Retry pass works on a copy: a framed record must be consumed per walk
		// (one record, one message) but `framed` itself keeps every record for
		// later retry re-frames. The copy is taken before the walk so records
		// consumed from `pool` mid-walk cannot be matched again as framed ones.
		const retryPool = [...framed];
		let matchedCount = 0;
		while (matchedCount < messages.length && pool.length + retryPool.length > 0) {
			const message = messages[messages.length - 1 - matchedCount];
			if (message.role !== "user") break;

			const poolIdx = pool.findLastIndex((record) => matchesRecord(message, record));
			if (poolIdx >= 0) {
				// Consumed into the current frame; keep a copy in `framed` for
				// retry safety.
				framed.push(...pool.splice(poolIdx, 1));
			} else {
				const framedIdx = retryPool.findLastIndex((record) => matchesRecord(message, record));
				if (framedIdx < 0) break;
				// Already in `framed` (shared object reference) — consume only
				// from the walk's copy, never push it into `framed` again.
				retryPool.splice(framedIdx, 1);
			}
			matchedCount++;
		}
		if (matchedCount === 0) return;

		// Write the unconsumed remainder back: records consumed above now live
		// in `framed`, so they must not stay pending (the status would keep
		// counting them and later walks would see them twice).
		if (matchedCount > 0) {
			pending = pool;
		}

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
	// A `length` stop reason also reports "completed", but pi can later
	// compact-and-retry such a response with the original steering messages,
	// so those records are kept too; agent_settled clears them if no retry
	// happens.
	pi.on("turn_end", async (event) => {
		if (event.outcome !== "completed" || framed.length === 0) return;
		// `stopReason` only exists on assistant messages; narrow first.
		const message = event.message;
		const isLength = message?.role === "assistant" && message.stopReason === "length";
		if (!isLength) framed = [];
	});

	// Abort returns queued messages to the editor natively; stale records must
	// never frame an unrelated future prompt. Settled also covers the normal
	// end of a run, clearing any leftovers.
	pi.on("agent_settled", async (_event, ctx) => {
		promptSkipArmed = false;
		if (pending.length === 0 && framed.length === 0) return;
		pending = [];
		framed = [];
		updateStatus(ctx);
	});

	pi.on("session_start", async (_event, ctx) => {
		pending = [];
		framed = [];
		runSawAssistant = false;
		promptSkipArmed = false;
		updateStatus(ctx);
	});
}
