/**
 * Ask User Tool - Claude Code style AskUserQuestion experience.
 *
 * - 1-4 questions in one dialog; header shows progress + answers so far
 * - Per question: options with descriptions, one marked `recommended: true`
 *   (preselected, tagged "★ Recommended"); number keys 1-9 quick-pick
 * - `multiSelect: true` questions: Space toggles checkboxes, 'a' toggles all,
 *   Enter confirms the selection
 * - "Other" option opens an inline editor for free text (Esc returns)
 * - "Chat / clarify first" option ends the dialog telling the model the user
 *   wants to discuss before deciding
 * - ← or Esc (after the first question) goes back to edit a previous answer
 * - Final review screen shows all answers before sending; Enter submits,
 *   select a question to re-edit it, Esc goes back
 * - Esc on the first question cancels
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
	Editor,
	type EditorTheme,
	Key,
	matchesKey,
	Text,
	visibleWidth,
	wrapTextWithAnsi,
} from "@earendil-works/pi-tui";
import { Type } from "typebox";

const CHAT_LABEL = "Chat / clarify first";
const OTHER_LABEL = "Other — type your answer";
const CONFIRM_LABEL = "✓ Confirm selection";

interface OptionWithDesc {
	label: string;
	description?: string;
	recommended?: boolean;
}

interface QuestionSpec {
	question: string;
	options: OptionWithDesc[];
	multiSelect?: boolean;
}

interface QAnswer {
	value: string | null;
	wasCustom: boolean;
	wasChat: boolean;
	multiValues: string[];
	customText: string;
}

interface AskDetails {
	questions: string[];
	answers: (string | null)[];
	wasCustom: boolean[];
	wasChat: boolean;
	chatIndex?: number;
}

const OptionSchema = Type.Object({
	label: Type.String({ description: "Display label for the option" }),
	description: Type.Optional(
		Type.String({ description: "Optional description shown below the label" }),
	),
	recommended: Type.Optional(
		Type.Boolean({
			description: "Mark this option as the recommended default (preselected)",
		}),
	),
});

const QuestionSchema = Type.Object({
	question: Type.String({ description: "The question to ask" }),
	options: Type.Array(OptionSchema, {
		description: "2-4 concrete options. Mark exactly one with recommended: true.",
	}),
	multiSelect: Type.Optional(
		Type.Boolean({
			description:
				"Allow choosing multiple options (Space to toggle, Enter to confirm). Only set when multiple answers genuinely make sense.",
		}),
	),
});

const AskParams = Type.Object({
	questions: Type.Array(QuestionSchema, {
		description:
			"1-4 questions asked in one dialog. The user previews all answers and can go back to edit before submitting.",
	}),
});

export default function askUser(pi: ExtensionAPI) {
	pi.registerTool({
		name: "ask_user",
		label: "Ask User",
		description:
			"Ask the user 1-4 questions in one dialog with selectable options. Mark one option per question as recommended (recommended: true); set multiSelect: true only when multiple answers make sense. The user can also type a free-text answer via 'Other', pick 'Chat / clarify first' to discuss before deciding, and reviews all answers (with a chance to edit) before they are sent. Use whenever a decision needs user input.",
		parameters: AskParams,
		executionMode: "sequential",

		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const questions: QuestionSpec[] = params.questions ?? [];
			if (ctx.mode !== "tui") {
				return {
					content: [
						{ type: "text", text: "Error: UI not available (non-interactive mode)" },
					],
					details: {
						questions: questions.map((q) => q.question),
						answers: questions.map(() => null),
						wasCustom: questions.map(() => false),
						wasChat: false,
					} as AskDetails,
				};
			}

			if (questions.length === 0 || questions.some((q) => q.options.length === 0)) {
				return {
					content: [{ type: "text", text: "Error: questions and options are required" }],
					details: {
						questions: questions.map((q) => q.question),
						answers: questions.map(() => null),
						wasCustom: questions.map(() => false),
						wasChat: false,
					} as AskDetails,
				};
			}

			const result = await ctx.ui.custom<{
				answers: QAnswer[];
				chatIndex?: number;
			} | null>(
				(tui, theme, _kb, done) => {
					const answers: QAnswer[] = questions.map(() => ({
						value: null,
						wasCustom: false,
						wasChat: false,
						multiValues: [],
						customText: "",
					}));

					// stage: "question" (answering q qi) | "review"
					let stage: "question" | "review" = "question";
					let qi = 0;
					let optionIndex = 0;
					let multiSet = new Set<number>();
					let editMode = false;
					let cachedLines: string[] | undefined;

					const editorTheme: EditorTheme = {
						borderColor: (s) => theme.fg("accent", s),
						selectList: {
							selectedPrefix: (t) => theme.fg("accent", t),
							selectedText: (t) => theme.fg("accent", t),
							description: (t) => theme.fg("muted", t),
							scrollInfo: (t) => theme.fg("dim", t),
							noMatch: (t) => theme.fg("warning", t),
						},
					};
					const editor = new Editor(tui, editorTheme);

					editor.onSubmit = (value) => {
						const trimmed = value.trim();
						if (trimmed) {
							record({
								value: trimmed,
								wasCustom: true,
								wasChat: false,
								multiValues: [],
								customText: trimmed,
							});
						} else {
							editMode = false;
							editor.setText("");
							refresh();
						}
					};

					function refresh() {
						cachedLines = undefined;
						tui.requestRender();
					}

					function enterQuestion(i: number, reEdit: boolean) {
						qi = i;
						stage = "question";
						const q = questions[i];
						const a = answers[i];
						const all = questionOptions(q);
						if (a.wasCustom) {
							editMode = true;
							editor.setText(a.customText);
							optionIndex = all.findIndex((o) => o.isOther === true); // Other row
						} else {
							editMode = false;
							editor.setText("");
							multiSet = new Set(a.multiValues.map((v) => q.options.findIndex((o) => o.label === v)).filter((x) => x >= 0));
							const rec = q.options.findIndex((o) => o.recommended === true);
							optionIndex = rec >= 0 ? rec : 0;
						}
						refresh();
					}

					function record(a: QAnswer, advance = true) {
						answers[qi] = a;
						editMode = false;
						if (advance) {
							if (qi + 1 < questions.length) {
								enterQuestion(qi + 1, false);
							} else {
								stage = "review";
								reviewIndex = 0;
							}
						}
						refresh();
					}

					function questionOptions(q: QuestionSpec) {
						const opts = [
							...q.options,
							{ label: OTHER_LABEL, isOther: true },
						] as (OptionWithDesc & { isOther?: boolean; isChat?: boolean })[];
						if (q.multiSelect) opts.push({ label: CONFIRM_LABEL });
						opts.push({ label: CHAT_LABEL, isChat: true });
						return opts;
					}

					function goBack() {
						if (editMode) {
							editMode = false;
							editor.setText("");
							refresh();
							return;
						}
						if (stage === "review") {
							stage = "question";
							enterQuestion(questions.length - 1, false);
							return;
						}
						if (qi > 0) {
							enterQuestion(qi - 1, true);
						} else {
							done(null); // Esc on first question cancels
						}
					}

					let reviewIndex = 0;

					function handleQuestionInput(data: string) {
						const q = questions[qi];
						const all = questionOptions(q);

						if (editMode) {
							if (matchesKey(data, Key.escape)) {
								goBack();
								return;
							}
							editor.handleInput(data);
							refresh();
							return;
						}

						if (matchesKey(data, Key.left)) {
							goBack();
							return;
						}
						if (matchesKey(data, Key.escape)) {
							goBack();
							return;
						}

						if (matchesKey(data, Key.up)) {
							optionIndex = Math.max(0, optionIndex - 1);
							refresh();
							return;
						}
						if (matchesKey(data, Key.down)) {
							optionIndex = Math.min(all.length - 1, optionIndex + 1);
							refresh();
							return;
						}

						const num = data.match(/^[1-9]$/);
						if (num) {
							const idx = Number(num[0]) - 1;
							if (idx < all.length) {
								optionIndex = idx;
								activate(idx);
							}
							return;
						}

						if (matchesKey(data, Key.space) && q.multiSelect) {
							const sel = all[optionIndex];
							if (!sel.isOther && !sel.isChat && sel.label !== CONFIRM_LABEL) toggleMulti(optionIndex);
							return;
						}

						if (data === "a" || data === "A") {
							if (q.multiSelect) {
								if (multiSet.size === q.options.length) {
									multiSet.clear();
								} else {
									multiSet = new Set(q.options.map((_, i) => i));
								}
								refresh();
							}
							return;
						}

						if (matchesKey(data, Key.enter)) {
							activate(optionIndex);
							return;
						}
					}

					function toggleMulti(idx: number) {
						if (multiSet.has(idx)) multiSet.delete(idx);
						else multiSet.add(idx);
						refresh();
					}

					function activate(idx: number) {
						const q = questions[qi];
						const all = questionOptions(q);
						const sel = all[idx];

						if (sel.isOther) {
							editMode = true;
							refresh();
							return;
						}
						if (sel.isChat) {
							done({ answers, chatIndex: qi });
							return;
						}
						if (q.multiSelect) {
							if (sel.label === CONFIRM_LABEL) {
								confirmMulti();
							} else {
								toggleMulti(idx);
							}
							return;
						}
						record({
							value: sel.label,
							wasCustom: false,
							wasChat: false,
							multiValues: [],
							customText: "",
						});
					}

					function confirmMulti() {
						const q = questions[qi];
						if (multiSet.size === 0) return; // need at least one
						const labels = [...multiSet].sort((a, b) => a - b).map((i) => q.options[i].label);
						record({
							value: labels.join(", "),
							wasCustom: false,
							wasChat: false,
							multiValues: labels,
							customText: "",
						});
					}

					function handleReviewInput(data: string) {
						if (matchesKey(data, Key.up)) {
							reviewIndex = Math.max(0, reviewIndex - 1);
							refresh();
							return;
						}
						if (matchesKey(data, Key.down)) {
							reviewIndex = Math.min(questions.length, reviewIndex + 1);
							refresh();
							return;
						}
						if (matchesKey(data, Key.left) || matchesKey(data, Key.escape)) {
							reviewIndex = questions.length;
							goBack();
							return;
						}
						if (matchesKey(data, Key.enter)) {
							if (reviewIndex === 0) {
								done({ answers });
							} else {
								enterQuestion(reviewIndex - 1, true);
							}
							return;
						}
					}

					function handleInput(data: string) {
						if (stage === "review") {
							handleReviewInput(data);
						} else {
							handleQuestionInput(data);
						}
					}

					function render(width: number): string[] {
						if (cachedLines) return cachedLines;

						const lines: string[] = [];
						const renderWidth = Math.max(1, width);

						function addWrapped(text: string) {
							lines.push(...wrapTextWithAnsi(text, renderWidth));
						}
						function addWrappedWithPrefix(prefix: string, text: string) {
							const prefixWidth = visibleWidth(prefix);
							if (prefixWidth >= renderWidth) {
								addWrapped(prefix + text);
								return;
							}
							const wrapped = wrapTextWithAnsi(text, renderWidth - prefixWidth);
							const continuationPrefix = " ".repeat(prefixWidth);
							for (let i = 0; i < wrapped.length; i++) {
								lines.push(`${i === 0 ? prefix : continuationPrefix}${wrapped[i]}`);
							}
						}

						lines.push(theme.fg("accent", "─".repeat(renderWidth)));

						if (stage === "question") {
							const q = questions[qi];
							// Header: progress + answers so far
							addWrappedWithPrefix(
								" ",
								theme.fg("accent", `Question ${qi + 1} of ${questions.length}`) +
									theme.fg("dim", q.multiSelect ? "  (multi-select: Space to toggle)" : ""),
							);
							lines.push("");
							addWrappedWithPrefix(" ", theme.fg("text", theme.bold(q.question)));
							lines.push("");

							const all = questionOptions(q);

							for (let i = 0; i < all.length; i++) {
								const opt = all[i];
								const selected = i === optionIndex && !editMode;
								const prefix = selected ? theme.fg("accent", "> ") : "  ";
								let marker = "";
								if (q.multiSelect && !opt.isOther && !opt.isChat && opt.label !== CONFIRM_LABEL) {
									marker = multiSet.has(i) ? theme.fg("success", "[x] ") : theme.fg("dim", "[ ] ");
								}
								let label = `${marker}${opt.label}`;
								if (opt.isOther && editMode) label += " ✎";
								if (opt.recommended && !q.multiSelect) label += theme.fg("success", "  ★ Recommended");
								const color = selected || (opt.isOther && editMode) ? "accent" : "text";
								addWrappedWithPrefix(prefix, theme.fg(color, `${label}`));

								if (opt.description) {
									addWrappedWithPrefix("     ", theme.fg("muted", opt.description));
								}
							}

							if (editMode) {
								lines.push("");
								addWrappedWithPrefix(" ", theme.fg("muted", "Your answer:"));
								for (const line of editor.render(Math.max(1, renderWidth - 2))) {
									lines.push(` ${line}`);
								}
							}

							// Preview of answered questions
							const answered = answers.filter((a) => a.value !== null).length;
							if (answered > 0) {
								lines.push("");
								for (let i = 0; i < questions.length; i++) {
									if (i === qi) continue;
									const a = answers[i];
									const label = a.value !== null
										? theme.fg("success", `✓ ${i + 1}. ${questions[i].question} → `) + theme.fg("text", a.value)
										: theme.fg("dim", `○ ${i + 1}. ${questions[i].question} (not answered)`);
									addWrappedWithPrefix(" ", label);
								}
							}

							lines.push("");
							if (editMode) {
								addWrappedWithPrefix(" ", theme.fg("dim", "Enter to submit • Esc to go back"));
							} else {
								const hints = ["↑↓ navigate", "Enter to select"];
								if (q.multiSelect) hints.splice(1, 1, "Space toggle", "Enter on ✓ Confirm");
								if (qi > 0 || answered > 0) hints.push("← back");
								if (qi === 0 && answered === 0) hints.push("Esc to cancel");
								addWrappedWithPrefix(" ", theme.fg("dim", hints.join(" • ")));
							}
						} else {
							// Review stage
							addWrappedWithPrefix(
								" ",
								theme.fg("accent", "Review your answers") +
									theme.fg("dim", "  (Enter to submit, select a question to edit)"),
							);
							lines.push("");
							for (let i = 0; i < questions.length; i++) {
								const selectedRow = reviewIndex - 1 === i;
								const a = answers[i];
								const qLabel = `${i + 1}. ${questions[i].question}`;
								const rowPrefix = selectedRow ? theme.fg("accent", "> ") : "  ";
								addWrappedWithPrefix(rowPrefix, theme.fg(selectedRow ? "accent" : "text", qLabel));
								const ans = a.value !== null ? a.value : theme.fg("warning", "(not answered)");
								addWrappedWithPrefix("     ", ans);
								if (a.wasCustom) {
									addWrappedWithPrefix("     ", theme.fg("muted", "(free text)"));
								}
							}
							lines.push("");
							const submitSelected = reviewIndex === 0;
							addWrappedWithPrefix(
								submitSelected ? theme.fg("success", "> ") : "  ",
								theme.fg(submitSelected ? "success" : "text", "✓ Submit answers"),
							);
							lines.push("");
							addWrappedWithPrefix(
								" ",
								theme.fg("dim", "↑↓ navigate • Enter select/submit • ← back"),
							);
						}

						lines.push(theme.fg("accent", "─".repeat(renderWidth)));
						cachedLines = lines;
						return lines;
					}

					// init first question
					{
						const q = questions[0];
						const rec = q.options.findIndex((o) => o.recommended === true);
						optionIndex = rec >= 0 ? rec : 0;
					}

					return {
						render,
						invalidate: () => {
							cachedLines = undefined;
						},
						handleInput,
					};
				},
			);

			const qTexts = questions.map((q) => q.question);
			const wasCustomArr = questions.map(() => false);

			if (!result) {
				return {
					content: [{ type: "text", text: "User cancelled the questions" }],
					details: {
						questions: qTexts,
						answers: questions.map(() => null),
						wasCustom: wasCustomArr,
						wasChat: false,
					} as AskDetails,
				};
			}

			const ans = result.answers;
			const isChat = result.chatIndex !== undefined;

			const summary = questions
				.map((q, i) => {
					const a = ans[i];
					if (!a || a.value === null) return `${i + 1}. ${q.question} → (not answered)`;
					const tag = a.wasCustom ? " (free text)" : a.wasChat ? " (chat requested)" : "";
					return `${i + 1}. ${q.question} → ${a.value}${tag}`;
				})
				.join("\n");

			if (isChat) {
				const chatIdx = result.chatIndex!;
				const answeredSoFar = ans
					.slice(0, chatIdx)
					.map((a, i) => (a.value !== null ? `${i + 1}. ${questions[i].question} → ${a.value}` : null))
					.filter(Boolean)
					.join("\n");
				return {
					content: [
						{
							type: "text",
							text:
								`User chose to discuss first at question ${chatIdx + 1}: they have questions or need more context before deciding. ` +
								`Explain the trade-offs, answer their questions, and re-ask the remaining questions when they are ready.` +
								(answeredSoFar ? `\nAnswers so far:\n${answeredSoFar}` : ""),
						},
					],
					details: {
						questions: qTexts,
						answers: ans.map((a) => a.value),
						wasCustom: ans.map((a) => a.wasCustom),
						wasChat: true,
						chatIndex: chatIdx,
					} as AskDetails,
				};
			}

			return {
				content: [{ type: "text", text: `User answers:\n${summary}` }],
				details: {
					questions: qTexts,
					answers: ans.map((a) => a.value),
					wasCustom: ans.map((a) => a.wasCustom),
					wasChat: false,
				} as AskDetails,
			};
		},

		renderCall(args, theme, _context) {
			let text = theme.fg("toolTitle", theme.bold("ask_user"));
			const qs: QuestionSpec[] = Array.isArray(args.questions) ? args.questions : [];
			if (qs.length) {
				const parts = qs.map((q, i) => {
					const opts = q.options.map((o) => `${o.label}${o.recommended ? " ★" : ""}`);
					const extras = q.multiSelect ? " [multi]" : "";
					return `${i + 1}. ${q.question}${extras}: ${opts.join(" · ")}`;
				});
				text += `\n${theme.fg("dim", `  ${parts.join(" | ")}`)}`;
			}
			return new Text(text, 0, 0);
		},

		renderResult(result, _options, theme, _context) {
			const details = result.details as AskDetails | undefined;
			if (!details) {
				const text = result.content[0];
				return new Text(text?.type === "text" ? text.text : "", 0, 0);
			}

			if (details.wasChat) {
				return new Text(
					theme.fg("success", "✓ ") +
						theme.fg("accent", `wants to discuss first (Q${(details.chatIndex ?? 0) + 1})`),
					0,
					0,
				);
			}

			const answered = details.answers.filter((a) => a !== null).length;
			if (answered === 0) {
				return new Text(theme.fg("warning", "Cancelled"), 0, 0);
			}

			const first = details.answers.find((a) => a !== null) ?? "";
			const more = answered > 1 ? theme.fg("muted", ` +${answered - 1} more`) : "";
			return new Text(theme.fg("success", "✓ ") + theme.fg("accent", first) + more, 0, 0);
		},
	});
}
