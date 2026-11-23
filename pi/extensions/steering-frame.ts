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
 *   the first user `message_end` consumes it — before any pending check, so
 *   an empty queue can never leave the guard armed to wrongly skip a later
 *   delivery — and while no assistant message exists yet, that message is
 *   the run's own prompt and correlation is skipped. Text comparison cannot
 *   work here because pi builds the starting message as
 *   `prompt + image hints` when images are attached, so the text never
 *   equals the raw prompt. Deliveries usually
 *   arrive after the run's first assistant message, but pi can also drain
 *   queued steers at the very start of a run or automatic continuation,
 *   before any assistant message exists — those correlate too; skipping all
 *   pre-assistant user messages would leave their records armed. Matching is
 *   two-pass with text priority: a delivery first tries pending records with
 *   non-empty text (prefix match; a text+image steer is one message, so
 *   image-bearing deliveries are eligible), then the image-only records
 *   (record has no text but images; any delivered image block matches, since
 *   pi's queue normalization appends generated hint text that is not user
 *   content) — so a mixed text+image delivery can never be stolen by a
 *   newer image-only record. Deliveries are FIFO, so:
 *   a delivery that matches a record binds to it (the record's text is
 *   updated to the final delivered text, the record is marked bound, and it
 *   stays pending until the context walk frames it); a delivery that matches
 *   nothing retires the oldest unbound pending record once any record is
 *   bound (a bound record belongs to a delivery already seen and still
 *   awaits its framing, so it is never retired), or the oldest record while
 *   nothing is bound yet — its delivery window has passed, and leaving it
 *   armed could falsely frame a later follow-up.
 *   Expanded skill/template steers therefore deliver unframed (benign).
 * - `context_with_system` frames the contiguous trailing run of user
 *   messages (down to the first non-user message, which bounds the walk so
 *   older prompts below recent tool activity can never be reached). Each
 *   message in the run is matched — newest first, with the same
 *   text-before-image priority — against pending records plus `framed`
 *   records (see retry below); unmatched messages stay raw in place, and
 *   each group of ADJACENT matched messages is folded into one framed user
 *   message (an all-matched run — the common case — produces a single
 *   frame). Pending records consumed by the walk are removed from `pending`
 *   (they now live in `framed`); framed records are consumed from a per-walk
 *   copy so one record cannot match several messages in one walk, while
 *   `framed` itself keeps them for retry.
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
	/**
	 * Whether a delivered message has been correlated to this record. Bound
	 * records stay in `pending` (the context walk moves them into `framed`),
	 * and the unmatched-delivery retirement rule never retires them.
	 */
	bound: boolean;
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
 * Text pass: does a delivered transcript message correspond to a steer record
 * that has text? The delivered text must prefix-match the record text
 * (trim-start on both sides; skill/template expansion can change the wording,
 * which is why unmatchable deliveries retire a record instead of sticking
 * around). An image-bearing delivery CAN match a text record — a steer text
 * plus an attached image is one message.
 */
function matchesTextRecord(deliveredMessage: AgentMessage, record: SteerRecord): boolean {
	const rawTrimmed = record.text.trim();
	if (rawTrimmed.length === 0) return false;
	const text = messageText(deliveredMessage);
	if (text.trim().length === 0) return false;
	const deliveredTrimmed = text.trimStart();
	return (
		deliveredTrimmed.startsWith(rawTrimmed) ||
		deliveredTrimmed.startsWith(rawTrimmed.replace(/\s+/g, " "))
	);
}

/**
 * Image pass: does a delivered transcript message correspond to an image-only
 * steer record (no text, images attached)? The delivered message only needs to
 * carry at least one image block; pi's queue normalization can append
 * image-hint text to the delivery, and that generated text is not user content,
 * so the delivered text is not required to be empty.
 */
function matchesImageRecord(deliveredMessage: AgentMessage, record: SteerRecord): boolean {
	if (record.text.trim().length > 0 || !record.hasImages) return false;
	return messageImages(deliveredMessage).length > 0;
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
		pending.push({ text, hasImages, bound: false });
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
		// starting message, so its text differs from the raw prompt. The guard
		// is consumed BEFORE the pending check: pi emits the starting prompt
		// before its initial queue drain, and an empty queue would otherwise
		// leave the guard armed to wrongly skip a later delivery in the same
		// run (a continuation-only `agent_start` resets `runSawAssistant`
		// without touching the guard).
		if (promptSkipArmed) {
			// Consume the guard on the first user message_end either way, so it
			// can never wrongly skip a later delivery.
			promptSkipArmed = false;
			if (!runSawAssistant) return; // this IS the run's starting prompt
		}
		if (pending.length === 0) return;

		// Text records take priority over image-only ones: a mixed text+image
		// delivery must bind to its own text record, not be stolen by a newer
		// image-only record that merely shares the image presence.
		let boundIdx = pending.findLastIndex((record) => matchesTextRecord(message, record));
		if (boundIdx < 0) {
			boundIdx = pending.findLastIndex((record) => matchesImageRecord(message, record));
		}
		if (boundIdx >= 0) {
			// Bind: remember the final delivered text so the context-time match
			// is exact even when skill/template expansion changed the wording.
			// The record stays pending (still awaiting its framing) and is now
			// marked bound so retirement can never remove it.
			const record = pending[boundIdx];
			record.text = messageText(message);
			record.hasImages = messageImages(message).length > 0 || record.hasImages;
			record.bound = true;
			return;
		}
		// FIFO: this delivery just arrived, so every record older than the
		// drain start was already offered a delivery. Once any record is bound,
		// the drain has started — retire the oldest UNBOUND record (typically a
		// skill/template-expanded steer) and never a bound one, which still
		// awaits its framing. With no bound record at all, this delivery
		// corresponds to the oldest record; retire it as before. If the
		// delivery actually belonged to another extension's injected message,
		// retiring one record is still the benign direction: a later delivery
		// then goes out unframed rather than a follow-up being falsely framed.
		if (pending.some((record) => record.bound)) {
			const unboundIdx = pending.findIndex((record) => !record.bound);
			if (unboundIdx < 0) return; // all bound: retire nothing
			pending.splice(unboundIdx, 1);
		} else {
			pending.shift();
		}
		// Retirement changed the pending count; refresh the status.
		updateStatus(ctx);
	});

	pi.on("context_with_system", async (event, ctx) => {
		if (pending.length === 0 && framed.length === 0) return;
		const messages = event.messages;

		// The walk is bounded to the contiguous trailing run of user messages
		// (down to the first non-user message), so older prompts below recent
		// tool activity can never be reached. Each message in the run is
		// matched newest-first against the available records — pending records
		// first (they are newer), then framed records — with the same
		// text-before-image priority as delivery correlation. Unmatched
		// messages stay raw and the walk continues, so a gap between two
		// matched messages (e.g. an expanded steer that delivered unframed)
		// cannot abandon the records behind it.
		let runStart = messages.length;
		while (runStart > 0 && messages[runStart - 1].role === "user") runStart--;
		const run = messages.slice(runStart);
		if (run.length === 0) return;

		const pool = [...pending];
		// Retry pass works on a copy: a framed record must be consumed per walk
		// (one record, one message) but `framed` itself keeps every record for
		// later retry re-frames. The copy is taken before the walk so records
		// consumed from `pool` mid-walk cannot be matched again as framed ones.
		const retryPool = [...framed];
		const matched = new Array<boolean>(run.length).fill(false);
		for (let i = run.length - 1; i >= 0; i--) {
			if (pool.length === 0 && retryPool.length === 0) break;
			const message = run[i];
			let poolIdx = pool.findLastIndex((record) => matchesTextRecord(message, record));
			if (poolIdx < 0) poolIdx = pool.findLastIndex((record) => matchesImageRecord(message, record));
			if (poolIdx >= 0) {
				// Consumed into the current frame; keep a copy in `framed` for
				// retry safety.
				framed.push(...pool.splice(poolIdx, 1));
				matched[i] = true;
				continue;
			}
			let framedIdx = retryPool.findLastIndex((record) => matchesTextRecord(message, record));
			if (framedIdx < 0) framedIdx = retryPool.findLastIndex((record) => matchesImageRecord(message, record));
			if (framedIdx < 0) continue; // unmatched: stays raw, walk keeps going
			// Already in `framed` (shared object reference) — consume only
			// from the walk's copy, never push it into `framed` again.
			retryPool.splice(framedIdx, 1);
			matched[i] = true;
		}
		if (!matched.some(Boolean)) return;

		// Write the unconsumed remainder back: records consumed above now live
		// in `framed`, so they must not stay pending (the status would keep
		// counting them and later walks would see them twice).
		pending = pool;

		// Retirement of delivered-but-unmatched records is handled by the
		// message_end correlation above, so nothing extra is needed here.

		// Build the replacement oldest-to-newest: each group of ADJACENT
		// matched messages becomes one framed block (an all-matched run — the
		// common case — produces a single merged frame), unmatched messages
		// stay raw in place.
		const segments: AgentMessage[] = [];
		let group: AgentMessage[] = [];
		const flushGroup = () => {
			if (group.length === 0) return;
			const images = group.flatMap((m) => messageImages(m));
			const frame = buildFrame(group);
			segments.push(
				images.length === 0
					? { role: "user", content: frame, timestamp: Date.now() }
					: {
							role: "user",
							content: [{ type: "text", text: frame }, ...images],
							timestamp: Date.now(),
						},
			);
			group = [];
		};
		for (let i = 0; i < run.length; i++) {
			if (matched[i]) {
				group.push(run[i]);
			} else {
				flushGroup();
				segments.push(run[i]);
			}
		}
		flushGroup();

		const next = [...messages.slice(0, runStart), ...segments];
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
