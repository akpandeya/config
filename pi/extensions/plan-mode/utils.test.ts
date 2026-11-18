// Tests for the plan-mode read-only command gate and SQL checks.
// Run: node pi/extensions/plan-mode/utils.test.ts (node strips types natively).
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { isSafeCommand, isReadOnlySql, extractTodoItems } from "./utils.ts";

// --- Session regressions: commands falsely blocked in the gambitflow session ---

test("paths containing /code/ are no longer treated as launching the editor", () => {
	assert.equal(
		isSafeCommand(
			'find /Users/x/code/personal/gambitflow/apps/backend -name "*german*" -path "*test*" -not -path "*/node_modules/*"',
		),
		true,
	);
	assert.equal(isSafeCommand('grep -rn "validatePracticeItem" /Users/x/code/backend --include="*.js" -l'), true);
	assert.equal(isSafeCommand("code app.ts"), false);
	assert.equal(isSafeCommand("vim file.txt"), false);
	assert.equal(isSafeCommand("nano /etc/hosts"), false);
});

test("redirects to /dev/null and fd dups are reads, not writes", () => {
	assert.equal(isSafeCommand("ls /a /b 2>/dev/null | head -60"), true);
	assert.equal(isSafeCommand("grep -rn x /a 2>/dev/null; echo done"), true);
	assert.equal(isSafeCommand("curl -s https://x >/dev/null 2>&1"), true);
	assert.equal(isSafeCommand("make 2>&1 >/dev/null"), false); // make not a read pattern anyway
	assert.equal(isSafeCommand("echo hi > /tmp/out.txt"), false);
	assert.equal(isSafeCommand("echo hi >> /tmp/out.txt"), false);
	assert.equal(isSafeCommand("echo hi >out"), false);
	assert.equal(isSafeCommand("echo hi &>log.txt"), false);
	assert.equal(isSafeCommand('grep "a>b" file.txt'), true); // > inside quotes
});

test("compound read pipelines pass; one mutating segment blocks everything", () => {
	assert.equal(isSafeCommand('grep -rn "answersMatch" /a/b.ts | head -30'), true);
	assert.equal(isSafeCommand("cat a.txt | sort | uniq -c | wc -l"), true);
	assert.equal(isSafeCommand("find . -name '*.ts' | xargs cat | wc -l"), true);
	assert.equal(isSafeCommand("ls; grep x f; du -sh ."), true);
	assert.equal(isSafeCommand("cat a && grep x b || echo none"), true);
	assert.equal(isSafeCommand("cat a && rm -rf /"), false);
	assert.equal(isSafeCommand("echo ok; touch /tmp/x"), false);
	assert.equal(isSafeCommand("grep x f | tee /tmp/copy"), false);
});

// --- holes closed ---

test("find -delete, gh api POST-style flags, psql -o stay blocked", () => {
	assert.equal(isSafeCommand("find . -name '*.tmp' -delete"), false);
	assert.equal(isSafeCommand("find . -name '*.tmp' | xargs rm"), false);
	assert.equal(isSafeCommand("gh api repos/x/y -f body=hi"), false);
	assert.equal(isSafeCommand("gh api repos/x/y -X POST"), false);
	assert.equal(isSafeCommand("gh api repos/x/y"), true);
	assert.equal(isSafeCommand('psql "service=x" -o /tmp/dump -c "select 1"'), false);
	assert.equal(isSafeCommand("echo $(node -e 'require(\"fs\").writeFileSync(\"x\",\"y\")')"), false);
	assert.equal(isSafeCommand("echo `rm -rf /`"), false);
	assert.equal(isSafeCommand("sed -i 's/a/b/' file"), false);
	assert.equal(isSafeCommand("yq -i '.a = 1' f.yaml"), false);
	assert.equal(isSafeCommand("yq '.a' f.yaml"), true);
});

// --- curl / http ---

test("curl GET/HEAD allowed, writes and other verbs blocked", () => {
	assert.equal(isSafeCommand("curl -sS https://api.example.com/items"), true);
	assert.equal(isSafeCommand("curl -sS -X GET https://api.example.com/items | jq ."), true);
	assert.equal(isSafeCommand("curl -I https://api.example.com"), true);
	assert.equal(isSafeCommand("curl -X POST https://api.example.com -H 'content-type: application/json'"), false);
	assert.equal(isSafeCommand("curl -d '{\"a\":1}' https://api.example.com"), false);
	assert.equal(isSafeCommand("curl -sSd x https://api.example.com"), false);
	assert.equal(isSafeCommand("curl -F file=@x https://api.example.com/upload"), false);
	assert.equal(isSafeCommand("curl -o /tmp/page.html https://example.com"), false);
	assert.equal(isSafeCommand("curl --data-binary @f https://x"), false);
});

// --- SQL tools ---

test("psql allows SELECT-class commands only", () => {
	assert.equal(isSafeCommand('psql "service=app-live" -c "select count(*) from users"'), true);
	assert.equal(isSafeCommand('psql "service=app-live" -c "select r.distribution_center_bob_code from t r order by 1"'), true);
	assert.equal(isSafeCommand('psql "service=x" -c "\\dt"'), true);
	assert.equal(isSafeCommand('psql "service=x" -c "explain select 1"'), true);
	assert.equal(isSafeCommand('psql "service=x" -c "update users set x = 1"'), false);
	assert.equal(isSafeCommand('psql "service=x" -c "delete from users"'), false);
	assert.equal(isSafeCommand('psql "service=x" -c "insert into t values (1)"'), false);
	assert.equal(isSafeCommand('psql "service=x" -c "drop table users"'), false);
	assert.equal(isSafeCommand('psql "service=x" -c "truncate users"'), false);
	assert.equal(isSafeCommand('psql "service=x" -c "select 1; update t set a = 1"'), false);
	assert.equal(isSafeCommand('psql "service=x" -c "select * from users for update"'), false);
	assert.equal(isSafeCommand('psql "service=x" -c "select setval(\'t_id_seq\', 5)"'), false);
	assert.equal(isSafeCommand('psql "service=x"'), false); // interactive — no payload
	assert.equal(isSafeCommand('psql "service=x" -c "select case when a then 1 else 2 end from t"'), true);
});

test("snow sql treats -c as connection, -q as query", () => {
	assert.equal(isSafeCommand('snow sql -c hf -q "select 1"'), true);
	assert.equal(isSafeCommand('snow sql -c hf -q "delete from t"'), false);
	assert.equal(isSafeCommand('snow sql -c hf -q "select 1" -o /tmp/out'), false);
});

test("hf-df and hf-photon check the inline SQL", () => {
	assert.equal(isSafeCommand('hf-df "select 1" --backend dbx --csv'), true);
	assert.equal(isSafeCommand('hf-df "drop table t" --backend dbx'), false);
	assert.equal(isSafeCommand('hf-photon -q "select 1 from t LATERAL VIEW OUTER explode(arr) AS x"'), true);
	assert.equal(isSafeCommand('hf-photon -q "insert into t values (1)"'), false);
});

test("SQL file arguments are read and checked", () => {
	const dir = mkdtempSync(join(tmpdir(), "plan-mode-test-"));
	const good = join(dir, "good.sql");
	const bad = join(dir, "bad.sql");
	writeFileSync(good, "-- a saved read query\nselect id, name from widgets;\n");
	writeFileSync(bad, "update widgets set name = 'x';\n");
	assert.equal(isSafeCommand(`psql "service=x" -f ${good}`), true);
	assert.equal(isSafeCommand(`psql "service=x" -f ${bad}`), false);
	assert.equal(isSafeCommand(`sqlite3 /tmp/db.sqlite "select * from t"`), true);
	assert.equal(isSafeCommand(`sqlite3 /tmp/db.sqlite "delete from t"`), false);
	assert.equal(isSafeCommand(`sqlite3 /tmp/db.sqlite .output /tmp/x`), false);
	rmSync(dir, { recursive: true, force: true });
});

// --- the innocuous extras ---

test("other benign read commands pass", () => {
	assert.equal(isSafeCommand("git blame -L 10,20 src/app.ts"), true);
	assert.equal(isSafeCommand("git branch"), true);
	assert.equal(isSafeCommand("git branch new-feature"), false);
	assert.equal(isSafeCommand("git remote -v"), true);
	assert.equal(isSafeCommand("git remote add origin url"), false);
	assert.equal(isSafeCommand("git rev-parse HEAD"), true);
	assert.equal(isSafeCommand("git tag"), true);
	assert.equal(isSafeCommand("git tag v1.2"), false);
	assert.equal(isSafeCommand("docker ps"), true);
	assert.equal(isSafeCommand("docker compose logs backend"), true);
	assert.equal(isSafeCommand("docker exec web sh"), false);
	assert.equal(isSafeCommand("kubectl get pods"), true);
	assert.equal(isSafeCommand("kubectl delete pod x"), false);
	assert.equal(isSafeCommand("crontab -l"), true);
	assert.equal(isSafeCommand("man curl"), true);
	assert.equal(isSafeCommand("tar -tf archive.tar.gz"), true);
	assert.equal(isSafeCommand("unzip -l archive.zip"), true);
	assert.equal(isSafeCommand("sha256sum file.bin"), true);
	assert.equal(isSafeCommand("ping -c 3 example.com"), true);
	assert.equal(isSafeCommand("ping example.com"), false); // never terminates on macOS
	assert.equal(isSafeCommand("dig +short example.com"), true);
	assert.equal(isSafeCommand("gh pr view 12"), true);
	assert.equal(isSafeCommand("gh pr create"), false);
	assert.equal(isSafeCommand("node --version"), true);
	assert.equal(isSafeCommand("node script.js"), false);
	assert.equal(isSafeCommand("python3 -c 'print(1)'"), false);
	assert.equal(isSafeCommand("bash -c 'echo hi'"), false);
	assert.equal(isSafeCommand("sudo cat /etc/hosts"), false);
	assert.equal(isSafeCommand(""), false);
});

// --- guard the existing extractions from regressions ---

test("plan extraction still works", () => {
	const items = extractTodoItems("Plan:\n1. First step\n2. Second step\n");
	assert.equal(items.length, 2);
	assert.equal(items[0]?.text, "First step");
});
