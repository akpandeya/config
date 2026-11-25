/**
 * Test extension for the orchestrator arm: replaces the real worker/reviewer with a scripted simulation.
 *
 * Env: ORCH_SCENARIO (path to scenario JSON), ORCH_LOG (path of the JSONL event log to append).
 * Registers `subagent` (agent, model, task) and `plan_done` (steps). Every call is logged. A worker brief that
 * lacks the step's required terms gets a BLOCKED reply (the real worker cannot see the conversation). After the
 * orchestrator finishes its turn with all steps done, the extension plays the review loop exactly like the real
 * plan-mode extension: it sends [REVIEW CHANGES REQUESTED] follow-ups with scripted findings, up to the round limit.
 */
import { readFileSync, appendFileSync, writeFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type Step = { text: string; needs: string[]; outcomes?: string[]; apply?: Record<string, string> };
type Finding = { text: string; needs: string[]; replace?: Record<string, [string, string]> };
type Round = { approved: boolean; findings?: Finding[] };
type Scenario = { steps: Step[]; review_limit: number; rounds: Round[]; fix_outcomes?: string[] };

export default function (pi: ExtensionAPI) {
	const scenario: Scenario = JSON.parse(readFileSync(process.env.ORCH_SCENARIO ?? "", "utf8"));
	const logPath = process.env.ORCH_LOG ?? "/dev/null";
	const log = (event: Record<string, unknown>) => appendFileSync(logPath, JSON.stringify({ t: Date.now(), ...event }) + "\n");
	const dispatchCount = new Map<number, number>();
	const done = new Set<number>();
	let phase: "execute" | "review" = "execute";
	let round = 0;
	let fixCalls = 0;
	let currentFindings: Finding[] = [];

	const esc = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	const first = (brief: string, term: string) => {
		const m = new RegExp("(?<![\\w])" + esc(term), "i").exec(brief);
		return m ? m.index : -1;
	};
	const has = (brief: string, terms: string[]) => terms.length === 0 || terms.some((t) => first(brief, t) >= 0);

	pi.on("tool_call", async (event) => {
		const name = (event as { toolName?: string }).toolName ?? "";
		if (name !== "subagent" && name !== "plan_done") log({ kind: "own_tool", name, input: (event as { input?: unknown }).input });
	});

	pi.registerTool({
		name: "subagent",
		label: "Subagent",
		description:
			'Dispatch a subagent. Use { "agent": "worker", "model": "<provider/id>", "task": "<self-contained brief>" }. The subagent cannot see this conversation.',
		parameters: Type.Object({
			agent: Type.String(),
			model: Type.Optional(Type.String()),
			task: Type.String(),
		}),
		async execute(_id, params) {
			const brief = String(params.task ?? "");
			if (phase === "review") {
				const wanted = currentFindings.filter((f) => has(brief, f.needs));
				const outcome = scenario.fix_outcomes?.[fixCalls] ?? "ok";
				fixCalls += 1;
				if (wanted.length > 0 && outcome === "ok") {
					for (const f of wanted)
						for (const [path, [from, to]] of Object.entries(f.replace ?? {})) {
							const text = readFileSync(path, "utf8");
							writeFileSync(path, text.split(from).join(to));
						}
				}
				const reply =
					wanted.length === 0
						? "BLOCKED: I cannot see the review findings. Tell me the file, the line and what to change."
						: outcome === "ok"
							? "Fixed the listed finding(s); tests pass."
							: "FAILED: " + outcome;
				log({ kind: "dispatch", phase, agent: params.agent, model: params.model, round, brief_chars: brief.length, brief, blocked: wanted.length === 0, reply });
				return { content: [{ type: "text", text: reply }], details: {} };
			}
			let best = -1;
			const labelled = /^\s*step\s*(\d+)/i.exec(brief);
			if (labelled && Number(labelled[1]) >= 1 && Number(labelled[1]) <= scenario.steps.length) best = Number(labelled[1]) - 1;
			let bestKey: [number, number] = [0, 0];
			scenario.steps.forEach((s, i) => {
				if (best >= 0 && labelled) return;
				const hits = s.needs.map((t) => first(brief, t)).filter((x) => x >= 0);
				if (hits.length === 0) return;
				const key: [number, number] = [0, -Math.min(...hits)];
				if (best < 0 || key[0] > bestKey[0] || (key[0] === bestKey[0] && key[1] > bestKey[1])) {
					best = i;
					bestKey = key;
				}
			});
			if (best < 0) {
				log({ kind: "dispatch", phase, agent: params.agent, brief_chars: brief.length, step: null, blocked: true });
				return { content: [{ type: "text", text: "BLOCKED: I cannot see the conversation and this brief does not name which step or files to change." }], details: {} };
			}
			const n = (dispatchCount.get(best) ?? 0) + 1;
			dispatchCount.set(best, n);
			const outcome = scenario.steps[best].outcomes?.[n - 1] ?? "ok";
			if (outcome === "ok") for (const [path, text] of Object.entries(scenario.steps[best].apply ?? {})) writeFileSync(path, text);
			const reply = outcome === "ok" ? "Done. Tests pass. Files now contain:\n" + Object.entries(scenario.steps[best].apply ?? {}).map(([p, t]) => `--- ${p}\n${t}`).join("\n") : outcome;
			log({ kind: "dispatch", phase, agent: params.agent, step: best + 1, attempt: n, brief_chars: brief.length, brief, model: params.model, reply });
			return { content: [{ type: "text", text: reply }], details: {} };
		},
	});

	pi.registerTool({
		name: "plan_done",
		label: "Plan step done",
		description: 'Mark plan steps completed, e.g. {"steps":[1]}. Call it right after a step is verifiably finished.',
		parameters: Type.Object({ steps: Type.Array(Type.Number()) }),
		async execute(_id, params) {
			for (const n of params.steps) done.add(n);
			log({ kind: "plan_done", steps: params.steps, completed: [...done] });
			return { content: [{ type: "text", text: `Recorded ${params.steps.join(",")}` }], details: {} };
		},
	});

	pi.on("agent_end", async () => {
		const total = scenario.steps.length;
		if (phase === "execute" && done.size < total) {
			log({ kind: "turn_end", phase, completed: [...done], note: "not all steps done; no review" });
			return;
		}
		if (phase === "execute") phase = "review";
		if (round >= scenario.rounds.length) return;
		const verdict = scenario.rounds[round];
		round += 1;
		log({ kind: "review", round, approved: verdict.approved, limit: scenario.review_limit });
		if (verdict.approved) return;
		if (round >= scenario.review_limit) {
			log({ kind: "review_limit_reached", round });
			return;
		}
		currentFindings = verdict.findings ?? [];
		const list = currentFindings.map((f) => `- ${f.text}`).join("\n");
		pi.sendMessage(
			{
				customType: "plan-review-fixes",
				content: `[REVIEW CHANGES REQUESTED]\n\nThe reviewer found issues with the implementation:\n\n${list}\n\nDelegate each fix to the \`worker\` subagent — do not implement fixes inline. Dispatch with { "agent": "worker", "model": "ai-model-router/GLM 5.3 Flash", "task": "<self-contained fix brief>" }; the brief cannot see this conversation, so include the finding, the file and line, and what to change. Do not restate the plan; make the changes and leave the plan steps complete so the review can run again.`,
				display: true,
			},
			{ triggerTurn: true, deliverAs: "followUp" },
		);
	});
}
