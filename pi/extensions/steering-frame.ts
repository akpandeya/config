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
 * Not implemented (on purpose): queue editing (↑). Pi's extension API does not
 * expose queue manipulation, so editing would require the extension to own the
 * whole queue, including abort behavior and skill/template expansion.
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { AgentMessage } from "@earendil-works/pi-agent-core";

interface PendingSteer {
	/** Raw text as typed, before skill/template expansion. */
	text: string;
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
 * Does the delivered transcript message correspond to a raw steer text?
 * Skill/template expansion can change the text, so this is a prefix check on
 * the trimmed text and may legitimately fail for expanded messages. A failed
 * match is safe: that message just stays unframed.
 */
function matchesSteer(delivered: string, raw: string): boolean {
	const deliveredTrimmed = delivered.trimStart();
	const rawTrimmed = raw.trim();
	if (rawTrimmed.length === 0) return false;
	return (
		deliveredTrimmed.startsWith(rawTrimmed) ||
		deliveredTrimmed.startsWith(rawTrimmed.replace(/\s+/g, " "))
	);
}

function buildFrame(messages: AgentMessage[]): string {
	const lines: string[] = [];
	const texts = messages.map((m) => messageText(m).trim()).filter((t) => t.length > 0);
	const count = messages.length;
	lines.push("<user-steering>");
	lines.push(
		`The following ${count} message${count === 1 ? "" : "s"} arrived from the user while you were working. Treat them as mid-task course corrections:`,
	);
	lines.push("- Address each message before continuing.");
	lines.push("- Adjust your plan or approach if the messages require it.");
	lines.push("- Continue the current task unless a message says otherwise.");
	lines.push("");
	if (texts.length === 0) {
		// Defensive: a matched message always has text (matching requires a
		// non-empty prefix), so this only guards a future refactor that loosens
		// the match. Image blocks are appended to the framed message separately.
		lines.push("(The messages carried no text content.)");
	} else {
		lines.push("Messages:");
		texts.forEach((text, i) => {
			const body = text.split("\n");
			body.forEach((line, j) => {
				lines.push(j === 0 ? `${i + 1}. ${line}` : `   ${line}`);
			});
		});
	}
	lines.push("</user-steering>");
	return lines.join("\n");
}

export default function steeringFrameExtension(pi: ExtensionAPI): void {
	/** Steered inputs awaiting delivery, in arrival order. */
	let pending: PendingSteer[] = [];

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
		pending.push({ text: event.text });
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

	pi.on("context_with_system", async (event, ctx) => {
		if (pending.length === 0) return;
		const messages = event.messages;

		// Walk backwards from the end, matching the trailing run of user
		// messages against the recorded steers in reverse arrival order.
		const reversed = [...pending].reverse();
		let matchedCount = 0;
		while (matchedCount < messages.length && matchedCount < reversed.length) {
			const message = messages[messages.length - 1 - matchedCount];
			if (message.role !== "user") break;
			if (!matchesSteer(messageText(message), reversed[matchedCount].text)) break;
			matchedCount++;
		}
		if (matchedCount === 0) {
			// Nothing at the tail corresponds to what we recorded. Leave the
			// flag armed: the boundary where the batch is delivered has not
			// happened yet (for example, delivery into the next run).
			return;
		}

		const start = messages.length - matchedCount;
		const batch = messages.slice(start);
		const images = batch.flatMap((m) => messageImages(m));
		const frame = buildFrame(batch);

		const framed: AgentMessage =
			images.length === 0
				? { role: "user", content: frame, timestamp: Date.now() }
				: {
						role: "user",
						content: [{ type: "text", text: frame }, ...images],
						timestamp: Date.now(),
					};

		const next = [...messages.slice(0, start), framed];
		pending = pending.slice(0, pending.length - matchedCount);
		updateStatus(ctx);
		return { messages: next };
	});

	// Abort returns queued messages to the editor natively; a stale record must
	// never frame an unrelated future prompt. Settled also covers the normal
	// end of a run, clearing any leftovers that were handled but never matched.
	pi.on("agent_settled", async (_event, ctx) => {
		if (pending.length === 0) return;
		pending = [];
		updateStatus(ctx);
	});

	pi.on("session_start", async (_event, ctx) => {
		pending = [];
		updateStatus(ctx);
	});
}
