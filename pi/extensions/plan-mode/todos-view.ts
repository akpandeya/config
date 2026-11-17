/**
 * Rendering for plan-mode todo lists.
 *
 * The widget above the editor is the only place the plan shows up while the
 * agent works, so every row it takes comes out of the transcript. Layout rules:
 *
 *  - Fill the terminal width: up to 4 columns, chosen so the longest step still
 *    fits on one line. A 290-column screen therefore shows 9 steps in 3 rows
 *    instead of 9 rows with a dead right margin.
 *  - Respect a hard row budget (MAX_WIDGET_ROWS). When the plan cannot fit even
 *    with the widest useful columns, fill the budget and point at /todos.
 *  - Always show step numbers: plan_done(n) is addressed by number, so a list
 *    without them cannot be reconciled with "marked step 4 done".
 */

import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { Component, KeybindingsManager, TUI } from "@earendil-works/pi-tui";
import { truncateToWidth, visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import type { TodoItem } from "./utils.ts";

type Theme = ExtensionContext["ui"]["theme"];

/** Hard row budget for the above-editor widget (plus one "N more" line). */
export const MAX_WIDGET_ROWS = 5;
const MAX_COLUMNS = 4;
/** Below this a column is too narrow to read, so prefer fewer columns. */
const MIN_COLUMN_WIDTH = 34;
/**
 * A column may clip the longest step, but not below this share of it: past that
 * point showing fewer steps in full beats showing all of them gutted.
 */
const MIN_READABLE_SHARE = 0.7;
const GUTTER = "   ";

function clamp(value: number, min: number, max: number): number {
	return Math.max(min, Math.min(max, value));
}

export function columnCount(width: number): number {
	const fit = Math.floor((width + GUTTER.length) / (MIN_COLUMN_WIDTH + GUTTER.length));
	return clamp(fit, 1, MAX_COLUMNS);
}

function columnWidth(width: number, columns: number): number {
	return Math.max(1, Math.floor((width - GUTTER.length * (columns - 1)) / columns));
}

/** Current step = first incomplete step; drives the ▸ marker. */
export function currentStep(items: TodoItem[]): number | undefined {
	return items.find((item) => !item.completed)?.step;
}

function stepText(item: TodoItem): string {
	return `${item.step}. ${item.text}`;
}

function stepLine(item: TodoItem, current: number | undefined, theme: Theme): string {
	const body = stepText(item);
	if (item.completed) {
		return `${theme.fg("success", "✓")} ${theme.fg("muted", theme.strikethrough(body))}`;
	}
	if (item.step === current) {
		return `${theme.fg("accent", "▸")} ${body}`;
	}
	return `${theme.fg("muted", "☐")} ${body}`;
}

function padTo(line: string, width: number): string {
	const pad = width - visibleWidth(line);
	return pad > 0 ? line + " ".repeat(pad) : line;
}

/**
 * Lay items out column-major (down the first column, then the next) so the plan
 * still reads in numeric order on a wide terminal.
 */
function renderGrid(items: TodoItem[], columns: number, width: number, theme: Theme): string[] {
	const current = currentStep(items);
	const perColumn = Math.ceil(items.length / columns);
	const buckets: string[][] = [];

	for (let column = 0; column < columns; column++) {
		const lines = items
			.slice(column * perColumn, (column + 1) * perColumn)
			.map((item) => truncateToWidth(stepLine(item, current, theme), width, "…"));
		if (lines.length > 0) buckets.push(lines);
	}

	const height = buckets.reduce((max, lines) => Math.max(max, lines.length), 0);
	const rows: string[] = [];
	for (let row = 0; row < height; row++) {
		rows.push(
			buckets
				.map((lines) => padTo(lines[row] ?? "", width))
				.join(GUTTER)
				.trimEnd(),
		);
	}
	return rows;
}

function overflowLine(hidden: number, width: number, theme: Theme): string {
	return truncateToWidth(
		theme.fg("dim", `⋯ ${hidden} more step${hidden === 1 ? "" : "s"} · /todos`),
		width,
		"…",
	);
}

function doneAboveLine(done: number, firstVisible: TodoItem | undefined, width: number, theme: Theme): string {
	const text = firstVisible === undefined ? `✓ ${done} done` : `✓ ${done} done · from step ${firstVisible.step}`;
	return truncateToWidth(theme.fg("dim", text), width, "…");
}

/** Rows for the above-editor widget. Empty when there is nothing to show. */
export function renderTodoWidget(
	items: TodoItem[],
	width: number,
	theme: Theme,
	maxRows = MAX_WIDGET_ROWS,
): string[] {
	if (items.length === 0 || width <= 0) return [];

	const maxColumns = columnCount(width);
	const rowsFor = (columns: number): number => Math.ceil(items.length / columns);
	const longest = items.reduce((max, item) => Math.max(max, visibleWidth(stepText(item)) + 2), 0);
	const readable = longest * MIN_READABLE_SHARE;

	// 1) Most columns that keep the row budget with no truncation at all.
	let columns: number | undefined;
	for (let candidate = maxColumns; candidate >= 1; candidate--) {
		if (rowsFor(candidate) <= maxRows && columnWidth(width, candidate) >= longest) {
			columns = candidate;
			break;
		}
	}

	// 2) Widest columns that keep the step text readable while clipping the tail.
	if (columns === undefined) {
		for (let candidate = 1; candidate <= maxColumns; candidate++) {
			if (rowsFor(candidate) <= maxRows && columnWidth(width, candidate) >= readable) {
				columns = candidate;
				break;
			}
		}
	}

	if (columns !== undefined) {
		return renderGrid(items, columns, columnWidth(width, columns), theme);
	}

	// 3) Too long for the budget: slide a window anchored on the current step, so
	// ticking a step scrolls the next one into view instead of burying it under
	// rows of completed work. Completed steps scroll off the top into a counted
	// header rather than being reordered to the bottom: the plan stays 1..N, so
	// plan_done(n) always maps to the same row.
	const firstOpen = items.findIndex((item) => !item.completed);
	const allDone = firstOpen === -1;
	// Everything done (transient, before agent_end clears the plan): show the tail.
	const anchor = allDone ? Math.max(0, items.length - (maxRows - 1) * maxColumns) : firstOpen;
	const hiddenAbove = items.slice(0, anchor);
	const rest = items.slice(anchor);
	if (rest.length === 0) return [];

	// Size the columns for the window's own text, not the whole plan's.
	const windowLongest = rest.reduce((max, item) => Math.max(max, visibleWidth(stepText(item)) + 2), 0);
	let fullColumns = 1;
	for (let candidate = maxColumns; candidate >= 1; candidate--) {
		if (columnWidth(width, candidate) >= windowLongest) {
			fullColumns = candidate;
			break;
		}
	}

	const gridWidth = columnWidth(width, fullColumns);
	const header =
		hiddenAbove.length > 0
			? [doneAboveLine(allDone ? items.length : hiddenAbove.length, allDone ? undefined : rest[0], width, theme)]
			: [];
	const budget = Math.max(1, maxRows - header.length);

	// Fit the remainder of the plan without a pointer row when it fits.
	const all = rest.slice(0, budget * fullColumns);
	if (all.length === rest.length) {
		return [...header, ...renderGrid(all, fullColumns, gridWidth, theme)];
	}

	// Otherwise keep the last row for the pointer to /todos.
	const shown = rest.slice(0, Math.max(1, (budget - 1) * fullColumns));
	return [
		...header,
		...renderGrid(shown, fullColumns, gridWidth, theme),
		overflowLine(rest.length - shown.length, width, theme),
	];
}

/** Every step on its own wrapped lines, for the /todos overlay. */
export function renderTodoDetail(items: TodoItem[], width: number, theme: Theme): string[] {
	const current = currentStep(items);
	return items.flatMap((item) => wrapTextWithAnsi(stepLine(item, current, theme), width));
}

/** Rows the /todos overlay scrolls through before paging. */
export const OVERLAY_PAGE_ROWS = 14;

/**
 * Scrollable full plan for /todos. Renders every step unwrapped by the widget
 * limits, with the current step marked and the footer pointing at the keys.
 */
export function createTodoOverlay(
	items: TodoItem[],
	deps: { tui: TUI; theme: Theme; keybindings: KeybindingsManager; done: () => void },
): Component & { handleInput(data: string): void } {
	const { tui, theme, keybindings, done } = deps;
	let offset = 0;
	let cachedWidth: number | undefined;
	let cachedLines: string[] | undefined;

	const invalidate = (): void => {
		cachedWidth = undefined;
		cachedLines = undefined;
	};

	return {
		render(width: number): string[] {
			if (cachedLines && cachedWidth === width) return cachedLines;
			cachedWidth = width;

			const completed = items.filter((item) => item.completed).length;
			const detail = renderTodoDetail(items, width, theme);
			offset = Math.min(offset, Math.max(0, detail.length - OVERLAY_PAGE_ROWS));
			const page = detail.slice(offset, offset + OVERLAY_PAGE_ROWS);
			const range =
				detail.length > OVERLAY_PAGE_ROWS
					? ` · lines ${offset + 1}-${offset + page.length} of ${detail.length}`
					: "";

			cachedLines = [
				theme.fg("accent", `Plan · ${completed}/${items.length} complete`),
				"",
				...page,
				"",
				theme.fg("dim", `↑/↓ scroll · esc/q/c close${range}`),
			];
			return cachedLines;
		},
		handleInput(data: string): void {
			if (keybindings.matches(data, "tui.select.cancel") || data === "q" || data === "c") {
				done();
				return;
			}
			if (keybindings.matches(data, "tui.select.up") || data === "k") {
				offset = Math.max(0, offset - 1);
			} else if (keybindings.matches(data, "tui.select.down") || data === "j") {
				offset += 1;
			} else {
				return;
			}
			invalidate();
			tui.requestRender();
		},
		invalidate,
	};
}
