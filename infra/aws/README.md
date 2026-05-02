# TradeSense on AWS (Fargate + EFS + Secrets Manager)

This is the production layout for the cash-account scalp bot. It keeps a
single 24/7 task with persistent compliance state (lots, wash carries, GFV
events) on EFS, and pulls Alpaca + Twilio + OpenAI keys from Secrets
Manager so they never live in the image or env files.

The bot runs the FastAPI app and the trading loop in the same container —
keep replica count at **1** so per-user `ComplianceService` state isn't
double-counted across nodes.

## 1. One-time setup

```bash
# Use the AWS CLI v2 with credentials that can create ECR / ECS / EFS.

# 1.1 ECR repo
aws ecr create-repository --repository-name tradesense

# 1.2 EFS file system + access point for /data
aws efs create-file-system --tags Key=Name,Value=tradesense-data
# After it's ready, note FileSystemId (fs-XXXX). Then:
aws efs create-access-point \
  --file-system-id fs-XXXX \
  --posix-user "Uid=1000,Gid=1000" \
  --root-directory '{"Path":"/tradesense","CreationInfo":{"OwnerUid":1000,"OwnerGid":1000,"Permissions":"0755"}}'

# 1.3 Secrets Manager — one secret per provider.
aws secretsmanager create-secret --name tradesense/alpaca --secret-string '{
  "ALPACA_API_KEY":"...",
  "ALPACA_SECRET_KEY":"...",
  "ALPACA_BASE_URL":"https://api.alpaca.markets",
  "ALPACA_DATA_FEED":"sip"
}'
aws secretsmanager create-secret --name tradesense/notify --secret-string '{
  "TELEGRAM_BOT_TOKEN":"...",
  "RESEND_API_KEY":"...",
  "TWILIO_ACCOUNT_SID":"...",
  "TWILIO_AUTH_TOKEN":"...",
  "TWILIO_WHATSAPP_FROM":"whatsapp:+14155238886"
}'
aws secretsmanager create-secret --name tradesense/ai --secret-string '{
  "OPENAI_API_KEY":"..."
}'
aws secretsmanager create-secret --name tradesense/auth --secret-string '{
  "SUPABASE_URL":"...",
  "SUPABASE_ANON_KEY":"...",
  "SUPABASE_JWT_SECRET":"...",
  "TRADESENSE_SECRET_KEY":"..."
}'
```

## 2. Build & push image

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

docker build -t tradesense:latest .
docker tag tradesense:latest "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/tradesense:latest"
docker push "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/tradesense:latest"
```

## 3. ECS Fargate task

See `task-definition.json.example` in this folder. Replace `ACCOUNT`,
`REGION`, `EFS_ID`, and the secret ARNs, then:

```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
aws ecs create-cluster --cluster-name tradesense
aws ecs create-service \
  --cluster tradesense \
  --service-name tradesense \
  --task-definition tradesense \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-...],securityGroups=[sg-...],assignPublicIp=ENABLED}" \
  --enable-execute-command
```

CloudWatch Logs picks up the task's stdout automatically (group name
configured in the task definition). For alerts, route Telegram + WhatsApp
from the bot itself (already wired in `notification_service.py`).

## 4. Going live with Alpaca Trader+ (SIP)

When the Alpaca subscription is active:

1. Update the `tradesense/alpaca` secret: set `ALPACA_DATA_FEED=sip`.
2. Roll the service: `aws ecs update-service --force-new-deployment ...`
3. Watch the first 30 minutes — re-tune `spread_filter_percent` if entries
   stall (SIP quotes are tighter and the existing thresholds may be
   conservative).

## 5. Real-money first week

Before flipping a user's `alpaca_paper_trading` to `false`:

- Confirm `FIRST_WEEK_REAL_MONEY_GUARD=true` and
  `FIRST_WEEK_PER_POSITION_USD=50` (already the defaults).
- Verify the EFS mount survives a task replace (kill the task; check that
  `compliance_state.json` is intact on the new task).
- Subscribe to Alpaca account-level webhooks if available; otherwise the
  bot's per-cycle account fetch is sufficient.

## 6. Shutdown / DR

```bash
aws ecs update-service --cluster tradesense --service tradesense --desired-count 0
```

EFS is durable; the task definition revision is reusable to bring the
service back up identically.
