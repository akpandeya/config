/**
 * Pure utility functions for plan mode.
 * Extracted for testability.
 *
 * Vendored from examples/extensions/plan-mode/utils.ts in
 * @earendil-works/pi-coding-agent 1.5.2 — see pi/README.md.
 */

import { readFileSync } from "node:fs";

// Destructive commands blocked in plan mode (and during review passes).
// Checked against every top-level command segment; a match anywhere blocks the
// whole invocation. Editors and shell redirects are handled separately below
// (an editor name inside a path segment like ~/code/... must not block every
// command on machines whose checkout lives under ~/code — observed live), and
// redirects to /dev/null are harmless reads that the old `>` regex blocked.
const DESTRUCTIVE_PATTERNS: RegExp[] = [
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
	/(^|\s)-delete(\s|$)/, // find -delete and friends
	/\bnpm\s+(install|uninstall|update|ci|link|publish)/i,
	/\byarn\s+(add|remove|install|publish)/i,
	/\bpnpm\s+(add|remove|install|publish)/i,
	/\bpip\s+(install|uninstall)/i,
	/\bapt(-get)?\s+(install|remove|purge|update|upgrade)/i,
	/\bbrew\s+(install|uninstall|upgrade)/i,
	/\bgit\s+(add|commit|push|pull|merge|rebase|reset|checkout|branch\s+-[dD]|stash|cherry-pick|revert|tag\s+(?!(-l|--list)(\s|$))|init|clone)/i,
	/\bsudo\b/i,
	/\bsu\b/i,
	/\bkill\b/i,
	/\bpkill\b/i,
	/\bkillall\b/i,
	/\breboot\b/i,
	/\bshutdown\b/i,
	/\bsystemctl\s+(start|stop|restart|enable|disable)/i,
	/\bservice\s+\S+\s+(start|stop|restart)/i,
];

// Editors only count as the command word of a segment (`code app.ts`), never
// as a path component (`~/code/personal/gambitflow/...`).
const EDITOR_COMMAND = /^\s*(?:vim?|vi|nano|emacs|code|subl|zed|hx|helix)\b/;

// Read-only commands allowed in plan mode and review. Every top-level segment
// (split on ; | && newline, quote-aware) must match one of these, so compound
// read pipelines (`grep x f | wc -l`, `find ... 2>/dev/null | head -60`) pass
// while any mutating segment blocks the whole invocation. Deny-by-default:
// interpreters (`node script.js`, `python -c`, `bash -c`) can write files, so
// they stay out regardless of the script's intent.
const READ_PATTERNS: RegExp[] = [
	// File reading / inspection
	/^\s*cat\b/,
	/^\s*head\b/,
	/^\s*tail\b/,
	/^\s*less\b/,
	/^\s*more\b/,
	/^\s*bat\b/,
	/^\s*zcat\b/,
	/^\s*bzcat\b/,
	/^\s*xzcat\b/,
	/^\s*sed\s+-n/i,
	/^\s*awk\b/,
	/^\s*grep\b/,
	/^\s*rg\b/,
	/^\s*find\b/,
	/^\s*fd\b/,
	/^\s*ls\b/,
	/^\s*eza\b/,
	/^\s*tree\b/,
	/^\s*stat\b/,
	/^\s*file\b/,
	/^\s*du\b/,
	/^\s*df\b/,
	/^\s*wc\b/,
	/^\s*diff\b/,
	/^\s*cmp\b/,
	/^\s*pwd\b/,
	/^\s*cd\b/,
	/^\s*echo\b/,
	/^\s*printf\b/,
	/^\s*man\b/,
	// Text-processing pipeline stages
	/^\s*sort\b/,
	/^\s*uniq\b/,
	/^\s*cut\b/,
	/^\s*tr\b/,
	/^\s*paste\b/,
	/^\s*comm\b/,
	/^\s*column\b/,
	/^\s*nl\b/,
	/^\s*tac\b/,
	/^\s*rev\b/,
	/^\s*fold\b/,
	/^\s*fmt\b/,
	/^\s*numfmt\b/,
	/^\s*expand\b/,
	/^\s*seq\b/,
	/^\s*jq\b/,
	/^(\s*base64)\b/,
	/^\s*iconv\b/,
	/^\s*xxd\b/,
	/^\s*hexdump\b/,
	/^\s*od\b/,
	/^\s*strings\b/,
	/^\s*(md5sum|sha1sum|sha256sum|sha512sum|shasum|cksum|b2sum)\b/,
	/^\s*(basename|dirname|readlink|realpath)\b/,
	// Archives: listing only (flag cluster must contain t, not c/x/u/r)
	/^\s*tar\s+(?=[-a-zA-Z]*t)(?!-[^ ]*[cxurA])\S+/,
	/^\s*tar\s+--list\b/,
	/^\s*unzip\s+(-l|-v|-Z)\b/,
	/^\s*zipinfo\b/,
	/^\s*gzip\s+-l\b/,
	// System / environment info
	/^\s*env\b/,
	/^\s*printenv\b/,
	/^\s*uname\b/,
	/^\s*whoami\b/,
	/^\s*id\b/,
	/^\s*groups\b/,
	/^\s*date\b/,
	/^\s*cal\b/,
	/^\s*uptime\b/,
	/^\s*hostname\b/,
	/^\s*tty\b/,
	/^\s*ps\b/,
	/^\s*free\b/,
	/^\s*lsof\b/,
	/^\s*netstat\b/,
	/^\s*ss\b/,
	/^\s*iostat\b/,
	/^\s*vmstat\b/,
	/^\s*which\b/,
	/^\s*whereis\b/,
	/^\s*type\b/,
	// Network reads (ping needs -c N: bare ping never terminates on macOS)
	/^\s*ping\s+(-\S+\s+)*-c\s+\d+/,
	/^\s*dig\b/,
	/^\s*nslookup\b/,
	/^\s*host\b/,
	/^\s*whois\b/,
	/^\s*wget\s+-O\s*-/,
	// Version probes
	/^\s*node\s+(-v|--version)\b/,
	/^\s*npm\s+(-v|--version)\b/,
	/^\s*python3?\s+(-V|--version)\b/,
	/^\s*git\s+(-v|--version)\b/,
	/^\s*psql\s+(-v|--version)\b/,
	/^\s*docker\s+(-v|--version)\b/,
	// Package managers: queries only
	/^\s*npm\s+(list|ls|view|info|search|outdated|audit)\b/,
	/^\s*yarn\s+(list|info|why|audit)\b/,
	/^\s*pip3?\s+(show|list|freeze|index|debug)\b/,
	/^\s*brew\s+(list|info|search|outdated|deps|uses|options)\b/,
	/^\s*apt\s+list\b/,
	/^\s*apt-cache\s+(search|policy|show)\b/,
	/^\s*dpkg\s+(-l|--list)\b/,
	// git: read subcommands only. Positional arguments create/move things
	// (`git branch newname`, `git remote add ...`), so list forms are
	// flags-only or bare.
	/^\s*git\s+(status|log|diff|show|blame|grep|shortlog|reflog|rev-parse|ls-files|ls-remote|describe|whatchanged)\b/,
	/^\s*git\s+branch(\s+-[^\s]+)*\s*$/,
	/^\s*git\s+remote(\s+-v)?\s*$/,
	/^\s*git\s+config\s+--(get|list)\b/,
	/^\s*git\s+worktree\s+list\b/,
	/^\s*git\s+tag(\s+(-l|--list))?\s*$/,
	// gh: read subcommands; `gh api` is GET-only via the check below
	/^\s*gh\s+(pr|issue|run|repo|release|gist|workflow)\s+(view|list|status|checks)\b/,
	/^\s*gh\s+(pr|issue)\s+comment\s+list\b/,
	// Jira CLI read-only lookups (create/edit/move/etc. never match)
	/^\s*jira\s+(view|list|issue\s+view|issue\s+list|board|sprint|comment\s+list)\b/,
	// Containers: reads only (exec/run/cp stay blocked)
	/^\s*docker\s+(ps|images|image\s+ls|logs|inspect|version|history|top|stats\s+--no-stream)\b/,
	/^\s*docker\s+compose\s+(ps|logs|config|top|images|port|version)\b/,
	// kubectl reads
	/^\s*kubectl\s+(get|describe|logs|version|config\s+(view|current-context)|cluster-info)\b/,
	// Cron / macOS system reads
	/^\s*crontab\s+-l\b/,
	/^\s*launchctl\s+list\b/,
	/^\s*defaults\s+read\b/,
	// xargs restricted to known read-only targets — bare xargs would let
	// `xargs bash -c ...` smuggle an arbitrary command past the segment check.
	/^\s*xargs\s+(?:(?:-0|-n\s+\d+|-I\s*\S+|--no-run-if-empty)\s+)*(cat|grep|ls|head|tail|wc|file|stat|du|basename|dirname|echo|printf|md5sum|sha256sum)\b/,
];

/** True when the segment's shell-level redirects all discard output
 * (`>/dev/null`, `2>&1`, `&>/dev/null`) or read input (`< file`, heredocs).
 * Any redirect into a real file is a mutation. Quote- and depth-aware so
 * `grep "a>b" file` and `awk '{print > "f"}'` are judged on the shell level
 * (the awk script's own redirect is a known accepted gap, as before). */
function hasMutatingRedirect(segment: string): boolean {
	let quote: string | undefined;
	let depth = 0;
	let i = 0;
	while (i < segment.length) {
		const ch = segment[i]!;
		if (quote) {
			if (quote === '"' && ch === "\\") {
				i += 2;
				continue;
			}
			if (ch === quote) quote = undefined;
			i++;
			continue;
		}
		if (ch === "'") {
			quote = ch;
			i++;
			continue;
		}
		if (ch === '"') {
			quote = ch;
			i++;
			continue;
		}
		if (ch === "\\") {
			i += 2;
			continue;
		}
		if (ch === "(") {
			depth++;
			i++;
			continue;
		}
		if (ch === ")" && depth > 0) {
			depth--;
			i++;
			continue;
		}
		if (ch === "<") {
			// Input redirect / heredoc / herestring / fd dup: reads, not writes.
			i++;
			continue;
		}
		if (ch === ">") {
			let j = i + 1;
			if (segment[j] === ">") j++; // >>
			if (segment[j] === "&" && /\d/.test(segment[j + 1] ?? "")) {
				i = j + 2; // >&1 fd dup
				continue;
			}
			while (j < segment.length && /\s/.test(segment[j]!)) j++;
			let target = "";
			while (j < segment.length && !/\s/.test(segment[j]!)) {
				target += segment[j]!;
				j++;
			}
			target = target.replace(/^"|"$/g, "").replace(/^'|'$/g, "");
			if (target !== "/dev/null") return true;
			i = j;
			continue;
		}
		if (ch === "&" && segment[i + 1] === ">") {
			// &> / &>> — resolve like > with the same /dev/null carve-out.
			let j = i + 2;
			if (segment[j] === ">") j++;
			while (j < segment.length && /\s/.test(segment[j]!)) j++;
			let target = "";
			while (j < segment.length && !/\s/.test(segment[j]!)) {
				target += segment[j]!;
				j++;
			}
			target = target.replace(/^"|"$/g, "").replace(/^'|'$/g, "");
			if (target !== "/dev/null") return true;
			i = j;
			continue;
		}
		i++;
	}
	return false;
}

/** Split a command into top-level segments on ; | && |& and newlines,
 * ignoring separators inside quotes, backticks and $(...) substitutions. */
export function splitCommandSegments(command: string): string[] {
	const segments: string[] = [];
	let current = "";
	let quote: string | undefined;
	let depth = 0;
	const push = () => {
		segments.push(current);
		current = "";
	};
	for (let i = 0; i < command.length; i++) {
		const ch = command[i]!;
		if (quote) {
			current += ch;
			if (quote === '"' && ch === "\\") {
				current += command[++i] ?? "";
			} else if (ch === quote) {
				quote = undefined;
			}
			continue;
		}
		if (ch === "'" || ch === '"') {
			quote = ch;
			current += ch;
			continue;
		}
		if (ch === "\\") {
			current += ch + (command[++i] ?? "");
			continue;
		}
		if (ch === "(") depth++;
		if (ch === ")" && depth > 0) depth--;
		if (depth === 0 && (ch === ";" || ch === "\n")) {
			push();
			continue;
		}
		if (depth === 0 && ch === "|") {
			if (command[i + 1] === "|" || command[i + 1] === "&") i++;
			push();
			continue;
		}
		if (depth === 0 && ch === "&" && command[i + 1] === "&") {
			push();
			i++;
			continue;
		}
		current += ch;
	}
	push();
	return segments;
}

/** Quote-aware whitespace tokenizer for flag/argument inspection. */
function tokenizeArgs(segment: string): string[] {
	const tokens: string[] = [];
	let token = "";
	let hasToken = false;
	let quote: string | undefined;
	const flush = () => {
		if (hasToken) tokens.push(token);
		token = "";
		hasToken = false;
	};
	for (let i = 0; i < segment.length; i++) {
		const ch = segment[i]!;
		if (quote === "'") {
			if (ch === "'") quote = undefined;
			else token += ch;
			continue;
		}
		if (quote === '"') {
			if (ch === '"') quote = undefined;
			else if (ch === "\\" && ['"', "\\", "$", "`"].includes(segment[i + 1] ?? "")) token += segment[++i]!;
			else token += ch;
			continue;
		}
		if (ch === "'" || ch === '"') {
			quote = ch;
			hasToken = true;
			continue;
		}
		if (ch === "\\") {
			token += segment[++i] ?? "";
			hasToken = true;
			continue;
		}
		if (/\s/.test(ch)) {
			flush();
			continue;
		}
		token += ch;
		hasToken = true;
	}
	flush();
	return tokens;
}

/** SQL statements allowed in plan mode: every ;-separated statement must
 * start with a read keyword (psql backslash meta-commands limited to the
 * \\d family and \\l), and no mutating keyword may appear anywhere. */
const DENY_SQL_PATTERN =
	/\b(insert|update|delete|drop|alter|truncate|create|replace|grant|revoke|copy|merge|call|perform|do|set|reset|begin|commit|rollback|abort|savepoint|release|prepare|execute|deallocate|vacuum|analyze|reindex|cluster|comment|lock|listen|notify|load|refresh|reassign|discard|setval|set_config|nextval|pg_sleep|for\s+update|for\s+share|for\s+no\s+key)\b/i;

export function isReadOnlySql(sql: string): boolean {
	// Strip comments first so a keyword inside one cannot skew the parse.
	const text = sql.replace(/--[^\n]*/g, " ").replace(/\/\*[\s\S]*?\*\//g, " ");
	// sqlite dot-commands (.output, .mode ...) can write; nothing is allowed.
	if (/^\s*\.\w/m.test(text)) return false;
	for (const statement of text.split(";")) {
		const trimmed = statement.trim();
		if (!trimmed) continue;
		// psql meta-commands: only the read-only \d family and \l.
		if (trimmed.startsWith("\\")) {
			if (!/^\\(?:d[a-z]*|l)\b/.test(trimmed)) return false;
			continue;
		}
		if (!/^(select|with|explain|show|describe|desc|table|values)\b/i.test(trimmed)) {
			if (!/^pragma\s+(table_|index_)/i.test(trimmed)) return false;
		}
		if (DENY_SQL_PATTERN.test(trimmed)) return false;
	}
	return true;
}

interface SqlToolConfig {
	match: RegExp;
	/** Flags whose value is inline SQL. */
	sqlFlags: string[];
	/** Flags whose value is a SQL file path. */
	fileFlags: string[];
	/** Other flags that consume the following token (ignored). */
	valueFlags: string[];
	/** What bare positional arguments mean. */
	positionals: "none" | "sql" | "file" | "dbfile-then-sql";
}

const SQL_TOOLS: SqlToolConfig[] = [
	{
		match: /^\s*psql\b/,
		sqlFlags: ["-c", "--command"],
		fileFlags: ["-f", "--file"],
		valueFlags: ["-h", "--host", "-p", "--port", "-U", "--username", "-d", "--dbname", "-v", "--set", "--variable"],
		positionals: "none",
	},
	{
		// snow sql: -c is the CONNECTION, -q the query.
		match: /^\s*snow\s+sql\b/,
		sqlFlags: ["-q", "--query"],
		fileFlags: ["-f", "--file"],
		valueFlags: ["-c", "--connection", "--account", "--warehouse", "--database", "--schema", "--role", "--username"],
		positionals: "none",
	},
	{
		// hf-sql <relpath> runs a saved query file from the workbench checkout.
		match: /^\s*hf-sql\b/,
		sqlFlags: [],
		fileFlags: [],
		valueFlags: [],
		positionals: "file",
	},
	{
		match: /^\s*hf-photon\b/,
		sqlFlags: ["-q", "-e", "-c"],
		fileFlags: ["-f", "--file"],
		valueFlags: [],
		positionals: "sql",
	},
	{
		match: /^\s*hf-df\b/,
		sqlFlags: ["-q", "-e"],
		fileFlags: ["-f", "--file"],
		valueFlags: ["--backend"],
		positionals: "sql",
	},
	{
		match: /^\s*sqlite3\b/,
		sqlFlags: [],
		fileFlags: [],
		valueFlags: ["-cmd", "-init"],
		positionals: "dbfile-then-sql",
	},
];

function readSqlFile(path: string): string | undefined {
	const root = process.env.HF_WORKBENCH_ROOT;
	const candidates = path.startsWith("/")
		? [path]
		: [
				...(root ? [`${root}/${path}`, `${root}/sql/${path}`] : []),
				`${process.cwd()}/${path}`,
			];
	for (const candidate of candidates) {
		try {
			return readFileSync(candidate, "utf8");
		} catch {
			// Try the next location; an unreadable file stays blocked.
		}
	}
	return undefined;
}

function sqlPayloadsAreReadOnly(config: SqlToolConfig, segment: string): boolean {
	const tokens = tokenizeArgs(segment);
	const payloads: string[] = [];
	const files: string[] = [];
	const positionals: string[] = [];
	const groups: Array<{ flags: string[]; sink: (value: string) => void }> = [
		{ flags: config.sqlFlags, sink: (value) => payloads.push(value) },
		{ flags: config.fileFlags, sink: (value) => files.push(value) },
		{ flags: config.valueFlags, sink: () => {} },
	];
	for (let i = 1; i < tokens.length; i++) {
		const token = tokens[i]!;
		if (token.startsWith("-")) {
			const flag = groups.flatMap(({ flags }) => flags).find((f) => token === f || token.startsWith(`${f}=`));
			if (flag !== undefined) {
				const group = groups.find(({ flags }) => flags.includes(flag))!;
				if (token.includes("=")) group.sink(token.slice(flag.length + 1));
				else {
					const value = tokens[++i];
					if (value === undefined) return false;
					group.sink(value);
				}
			}
			// Unknown flags are treated as boolean; a following value token then
			// lands in positionals and fails the SQL check (deny-safe).
			continue;
		}
		positionals.push(token);
	}
	// psql -o / snow sql -o redirect query output into a file — a write.
	if (tokens.slice(1).some((t) => t === "-o" || t === "--output")) return false;
	switch (config.positionals) {
		case "sql":
			payloads.push(...positionals);
			break;
		case "file":
			files.push(...positionals);
			break;
		case "dbfile-then-sql":
			if (positionals.length >= 2) payloads.push(positionals[1]!);
			break;
		case "none":
			break;
	}
	if (payloads.length === 0 && files.length === 0) return false;
	return (
		payloads.every(isReadOnlySql) &&
		files.every((file) => {
			const content = readSqlFile(file);
			return content !== undefined && isReadOnlySql(content);
		})
	);
}

const CURL_WRITE_FLAGS = new Set([
	"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii",
	"--json", "-F", "--form", "--form-string", "-T", "--upload-file",
	"-o", "--output", "-O", "--remote-name", "--remote-name-all", "-J", "--remote-header-name",
	"-c", "--cookie-jar", "-D", "--dump-header", "-K", "--config", "--create-dirs",
]);

function httpMethodIsRead(method: string | undefined): boolean {
	return method === undefined || /^(GET|HEAD)$/i.test(method);
}

/** curl is read-only when it sends GET/HEAD and writes nothing anywhere. */
function curlIsReadOnly(segment: string): boolean {
	const tokens = tokenizeArgs(segment);
	for (let i = 1; i < tokens.length; i++) {
		const token = tokens[i]!;
		if (CURL_WRITE_FLAGS.has(token)) return false;
		if (token.includes("=") && CURL_WRITE_FLAGS.has(token.slice(0, token.indexOf("=")))) return false;
		if (token === "-X" || token === "--request") {
			if (!httpMethodIsRead(tokens[++i])) return false;
		} else if (/^-[X][A-Za-z]/.test(token)) {
			if (!httpMethodIsRead(token.slice(2))) return false;
		} else if (token.startsWith("--request=")) {
			if (!httpMethodIsRead(token.slice("--request=".length))) return false;
		} else if (/^-[A-Za-z]*[dFT]/.test(token)) {
			// Combined short flags smuggle a data/form/upload flag (-sd, -sSd, ...).
			return false;
		}
	}
	return true;
}

/** gh api defaults to GET; -f/-F/--field force POST and --input posts a file. */
function ghApiIsReadOnly(segment: string): boolean {
	const tokens = tokenizeArgs(segment);
	for (let i = 1; i < tokens.length; i++) {
		const token = tokens[i]!;
		if (["-f", "-F", "--field", "--raw-field", "--input"].includes(token)) return false;
		if (token === "-x" || token === "-X" || token === "--method") {
			if (!httpMethodIsRead(tokens[++i])) return false;
		}
	}
	return true;
}

/** Tool-specific read checks. undefined = no special handling, fall through
 * to READ_PATTERNS. */
function specialReadCheck(segment: string): boolean | undefined {
	if (/^\s*yq\b/.test(segment)) return !/(^|\s)(-i|--inplace)\b/.test(segment);
	if (/^\s*curl\b/.test(segment)) return curlIsReadOnly(segment);
	if (/^\s*gh\s+api\b/.test(segment)) return ghApiIsReadOnly(segment);
	for (const config of SQL_TOOLS) {
		if (config.match.test(segment)) return sqlPayloadsAreReadOnly(config, segment);
	}
	return undefined;
}

/** Command substitution and process substitution contents run as commands in
 * their own right, so they get the same segment checks (recursively) instead
 * of hiding behind the outer command's read pattern (`echo $(node -e ...)`). */
function substitutionInners(segment: string): string[] {
	const inners: string[] = [];
	let quote: string | undefined;
	let i = 0;
	while (i < segment.length) {
		const ch = segment[i]!;
		if (quote) {
			if (quote === '"' && ch === "\\") i += 2;
			else {
				if (ch === quote) quote = undefined;
				i++;
			}
			continue;
		}
		if (ch === "'" || ch === '"') {
			quote = ch;
			i++;
			continue;
		}
		if (ch === "\\") {
			i += 2;
			continue;
		}
		const opener =
			(ch === "$" && segment[i + 1] === "(") ||
			((ch === "<" || ch === ">") && segment[i + 1] === "(") ||
			(ch === "`");
		if (!opener) {
			i++;
			continue;
		}
		const start = ch === "`" ? i + 1 : i + 2;
		let depth = 1;
		let j = start;
		let innerQuote: string | undefined;
		while (j < segment.length) {
			const c = segment[j]!;
			if (innerQuote) {
				if (c === innerQuote) innerQuote = undefined;
			} else if (c === "'" || c === '"') {
				innerQuote = c;
			} else if (c === "(") {
				depth++;
			} else if (c === ")") {
				depth--;
				if (depth === 0) break;
			} else if (c === "`" && ch === "`") {
				break;
			}
			j++;
		}
		if (j < segment.length || ch === "`") {
			inners.push(segment.slice(start, ch === "`" ? j : j));
			i = j + 1;
		} else {
			i = start;
		}
	}
	return inners;
}

function segmentPasses(segment: string): boolean {
	if (EDITOR_COMMAND.test(segment)) return false;
	if (DESTRUCTIVE_PATTERNS.some((pattern) => pattern.test(segment))) return false;
	if (hasMutatingRedirect(segment)) return false;
	const special = specialReadCheck(segment);
	if (special !== undefined) return special;
	return READ_PATTERNS.some((pattern) => pattern.test(segment));
}

/** Read-only gate for plan mode and review passes: every top-level segment
 * must be a read (deny-by-default), every redirect must discard output, and
 * command/process substitutions must themselves pass the same checks. */
export function isSafeCommand(command: string): boolean {
	const segments = splitCommandSegments(command).map((s) => s.trim());
	if (segments.every((s) => s === "")) return false;
	for (const segment of segments) {
		if (!segment) continue;
		if (!segmentPasses(segment)) return false;
		for (const inner of substitutionInners(segment)) {
			if (!isSafeCommand(inner)) return false;
		}
	}
	return true;
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
