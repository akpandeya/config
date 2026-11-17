/**
 * Read-Only Bash Extension — local-only (no upstream counterpart)
 *
 * Opt-in bash restriction for child pi processes, driven by a CLI flag instead
 * of session state: the subagent extension passes --readonly-bash to a child
 * when the dispatched agent's frontmatter sets bashAllowlist (see
 * pi/extensions/subagent/README.md).
 *
 * Why: a child agent (e.g. the read-only `reviewer`) is only PROMPT-constrained
 * to keep bash read-only. File edits are already impossible (its tools list has
 * no edit/write/subagent), but bash itself is a gap — a misbehaving dispatcher
 * could still get the child to run mutating commands. With the flag set, this
 * extension tool-enforces the same allowlist plan mode uses, so the child's
 * bash is blocked, not just requested read-only.
 *
 * Fail closed: an error from the flag lookup or the allowlist check blocks the
 * command rather than letting it through.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isSafeCommand } from "./plan-mode/utils.ts";

export default function readonlyBashExtension(pi: ExtensionAPI): void {
	pi.registerFlag("readonly-bash", {
		description: "Restrict bash to read-only commands; blocks everything else via tool_call",
		type: "boolean",
		default: false,
	});

	pi.on("tool_call", (event) => {
		if (event.toolName !== "bash") return;

		let enabled: boolean;
		try {
			enabled = pi.getFlag("readonly-bash") === true;
		} catch {
			enabled = true; // fail closed: a broken flag lookup must not un-restrict bash
		}
		if (!enabled) return;

		// Coerce inside the guarded region: a command value that throws during
		// stringification must produce a clean block, not escape the hook.
		let safe: boolean;
		let display: string;
		try {
			const command = (event.input as { command?: unknown }).command;
			const text = typeof command === "string" ? command : String(command);
			safe = isSafeCommand(text);
			display = text;
		} catch {
			safe = false; // fail closed
			display = "(unstringifiable command)";
		}
		if (!safe) {
			return {
				block: true,
				reason: `Read-only bash: command not allowlisted.\nCommand: ${display}`,
			};
		}
	});
}
