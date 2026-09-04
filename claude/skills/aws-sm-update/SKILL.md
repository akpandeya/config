---
name: aws-sm-update
description: Read or update a key in an AWS Secrets Manager secret using the sso-hf-secrets profile.
allowed-tools: Bash
---

Read or update a key in an AWS Secrets Manager secret.

## Profile

Always use `--profile sso-hf-secrets` and `--region eu-west-1`.

## Arguments

- `<secret-id> <key>` — read the current value of a key
- `<secret-id> <key> <value>` — update a key to a new value

If no arguments provided, ask the user for secret ID, key, and optionally new value.

## Read a key

```bash
aws secretsmanager get-secret-value \
  --secret-id <secret-id> \
  --region eu-west-1 \
  --profile sso-hf-secrets \
  --output json | python3 -c "
import sys, json
d = json.loads(json.load(sys.stdin)['SecretString'])
print(d['<key>'])
"
```

## Update a key

Use a temp file to avoid shell quoting issues with multiline values (e.g. private keys):

```bash
aws secretsmanager get-secret-value \
  --secret-id <secret-id> \
  --region eu-west-1 \
  --profile sso-hf-secrets \
  --output json | python3 -c "
import sys, json
d = json.loads(json.load(sys.stdin)['SecretString'])
d['<key>'] = '<value>'
print(json.dumps(d))
" > /tmp/sm-updated.json

aws secretsmanager put-secret-value \
  --secret-id <secret-id> \
  --region eu-west-1 \
  --profile sso-hf-secrets \
  --secret-string file:///tmp/sm-updated.json

rm /tmp/sm-updated.json
```

Then verify by reading the key back.

## Error handling

- `Token has expired` → tell user to run: `! aws sso login --profile sso-hf-secrets`
- `AccessDeniedException` → user needs `SecretsDeveloper` role on account `488514412228`
- Never print the full secret JSON — only the specific key being read or confirmed.
