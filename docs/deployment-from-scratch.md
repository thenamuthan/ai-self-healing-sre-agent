# AI-Powered Self-Healing SRE Agent
## Zero-to-100 Deployment Guide | Windows PowerShell + AWS CLI

**Validated architecture:** Datadog → Lambda1 → SQS → Lambda2 → Gemini + S3 Runbook → Guardrail → SSM → EC2 → RCA

**Validated region:** `us-east-2` after an earlier implementation in `us-east-1`

> **Security:** Rotate the Datadog API key that appeared during troubleshooting. Never commit AWS credentials, Gemini keys, Datadog keys, presigned URLs, private email addresses, or unredacted screenshots.

---

# 1. Validated outcomes

| Priority | Scenario | Behavior | Evidence |
|---|---|---|---|
| P1 | Disk | SNS escalation, no auto-heal, RCA | `ESCALATED` |
| P2 | Memory | DynamoDB approval request, no auto-heal, RCA | `PENDING_APPROVAL` |
| P3 | CPU | Gemini `cpu_autoheal`, guardrail, SSM | `CPU_AUTOHEAL_DONE` |
| P4 | Nginx service | Gemini `service_autoheal`, guardrail, SSM | `active`, `REMEDIATION_COMPLETED` |

# 2. Responsibility map

- **Datadog Agent and monitors:** collect metrics and send P1/P2/P3/P4 notifications.
- **Lambda1 (`sre-agent-alert-parser`):** public webhook receiver, normalizes the payload, injects `TARGET_INSTANCE_ID`, and sends to SQS.
- **SQS:** buffers alerts and triggers Lambda2.
- **Lambda2 (`sre-agent-bedrock-orchestrator`):** severity routing, runbook retrieval, Gemini decision, command guardrail, circuit breaker, SSM execution, and RCA generation.
- **S3:** stores `runbooks/` and `rca/` objects.
- **DynamoDB:** circuit-breaker attempt state and P2 approval requests.
- **SNS:** P1 email escalation.
- **Secrets Manager:** Gemini API key.
- **SSM:** approved remote command execution without SSH.
- **CloudWatch Logs:** created automatically when each Lambda first runs.

# 3. Deployment variables

```powershell
$REGION = "us-east-2"
$ACCOUNT_ID = "564711065576"
$BUCKET = "sre-agent-runbooks-$ACCOUNT_ID-use2"
$QUEUE_NAME = "sre-agent-orchestrator-queue"
$CIRCUIT_TABLE = "sre-agent-circuit-breaker"
$APPROVAL_TABLE = "sre-agent-approval-requests"
$SNS_TOPIC = "sre-agent-p1-escalation"
$LAMBDA1 = "sre-agent-alert-parser"
$LAMBDA2 = "sre-agent-bedrock-orchestrator"
$EC2_NAME = "sre-agent-demo-server"
$EC2_TYPE = "t3.micro"
$GEMINI_SECRET = "sre-agent/google-api-key"
$GEMINI_MODEL = "gemini-3.6-flash"
```

# 4. Workstation and repository

```powershell
aws configure
aws sts get-caller-identity
aws configure get region

git clone <YOUR_PRIVATE_REPOSITORY_HTTPS_URL>
Set-Location .\ai-self-healing-sre-agent
Get-ChildItem
```

Use a **private repository** until all sensitive content has been reviewed.

# 5. S3 and runbooks

```powershell
aws s3api create-bucket `
--bucket $BUCKET `
--region $REGION `
--create-bucket-configuration LocationConstraint=$REGION

aws s3 cp .\runbooks\ "s3://$BUCKET/runbooks/" `
--recursive `
--region $REGION

aws s3 ls "s3://$BUCKET/runbooks/" `
--recursive `
--region $REGION
```

Required exact keys:

```text
runbooks/cpu-spike-runbook.md
runbooks/memory-leak-runbook.md
runbooks/disk-full-runbook.md
runbooks/service-down-runbook.md
```

# 6. DynamoDB

```powershell
aws dynamodb create-table `
--table-name $CIRCUIT_TABLE `
--attribute-definitions AttributeName=incident_id,AttributeType=S `
--key-schema AttributeName=incident_id,KeyType=HASH `
--billing-mode PAY_PER_REQUEST `
--region $REGION

aws dynamodb create-table `
--table-name $APPROVAL_TABLE `
--attribute-definitions AttributeName=request_id,AttributeType=S `
--key-schema AttributeName=request_id,KeyType=HASH `
--billing-mode PAY_PER_REQUEST `
--region $REGION

aws dynamodb list-tables --region $REGION
```

# 7. SNS P1 escalation

```powershell
$SNS_ARN = aws sns create-topic `
--name $SNS_TOPIC `
--region $REGION `
--query TopicArn `
--output text

aws sns subscribe `
--topic-arn $SNS_ARN `
--protocol email `
--notification-endpoint "<EMAIL_ADDRESS>" `
--region $REGION
```

Confirm the email subscription before P1 testing.

# 8. Gemini key and Secrets Manager

Validate the key first:

```powershell
$API_KEY = "<GEMINI_API_KEY>"
Invoke-RestMethod `
-Method GET `
-Uri "https://generativelanguage.googleapis.com/v1beta/models?key=$API_KEY"
```

Store it:

```powershell
aws secretsmanager create-secret `
--name $GEMINI_SECRET `
--secret-string $API_KEY `
--region $REGION
```

The final validated model was `gemini-3.6-flash`. If a model returns HTTP 404, list the models available to the key and use a model supported for content generation.

# 9. SQS

```powershell
$QUEUE_URL = aws sqs create-queue `
--queue-name $QUEUE_NAME `
--attributes VisibilityTimeout=360 `
--region $REGION `
--query QueueUrl `
--output text

$QUEUE_ARN = aws sqs get-queue-attributes `
--queue-url $QUEUE_URL `
--attribute-names QueueArn `
--region $REGION `
--query Attributes.QueueArn `
--output text
```

Lambda2 timeout is 300 seconds. The SQS visibility timeout was set to 360 seconds because AWS rejected a 30-second visibility timeout.

# 10. IAM

IAM is account-level. Reuse an existing role only after validating its policy.

```powershell
aws iam get-role --role-name sre-agent-lambda-role

# If missing:
aws iam create-role `
--role-name sre-agent-lambda-role `
--assume-role-policy-document file://iam/lambda-trust-policy.json

aws iam put-role-policy `
--role-name sre-agent-lambda-role `
--policy-name sre-agent-inline-policy `
--policy-document file://iam/lambda-permissions.json

$LAMBDA_ROLE_ARN = aws iam get-role `
--role-name sre-agent-lambda-role `
--query Role.Arn `
--output text
```

Lambda policy must include:

- CloudWatch Logs create/write
- SQS send/receive/delete/get attributes
- SSM `SendCommand`, `GetCommandInvocation`, `ListCommandInvocations`
- DynamoDB `GetItem`, `PutItem`, `UpdateItem`, `DeleteItem`
- S3 `ListBucket`, `GetObject`, and **`PutObject`**
- SNS `Publish`
- Secrets Manager **`GetSecretValue`**

Create SSM instance role/profile:

```powershell
aws iam create-role `
--role-name sre-agent-ec2-ssm-role `
--assume-role-policy-document file://ec2-trust-policy.json

aws iam attach-role-policy `
--role-name sre-agent-ec2-ssm-role `
--policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

aws iam create-instance-profile `
--instance-profile-name sre-agent-ec2-profile

aws iam add-role-to-instance-profile `
--instance-profile-name sre-agent-ec2-profile `
--role-name sre-agent-ec2-ssm-role
```

# 11. EC2, security group, and user data

Discover eligible types instead of assuming `t2.micro`:

```powershell
aws ec2 describe-instance-types `
--filters Name=free-tier-eligible,Values=true `
--region $REGION `
--query "InstanceTypes[*].InstanceType"
```

The validated deployment selected **`t3.micro`** with Amazon Linux 2023 x86_64.

Create the security group and open HTTP for the demo:

```powershell
$SG_ID = aws ec2 create-security-group `
--group-name sre-agent-sg `
--description "SRE Agent Security Group" `
--region $REGION `
--query GroupId `
--output text

aws ec2 authorize-security-group-ingress `
--group-id $SG_ID `
--protocol tcp `
--port 80 `
--cidr 0.0.0.0/0 `
--region $REGION
```

Port 22 is not needed because administration uses SSM. Restrict the port 80 CIDR in non-demo environments.

`userdata.sh`:

```bash
#!/bin/bash
set -euxo pipefail
dnf update -y
dnf install -y nginx stress-ng
systemctl enable nginx
systemctl start nginx
echo "SRE Agent Test Server" > /usr/share/nginx/html/index.html
```

Launch:

```powershell
$AMI_ID = aws ssm get-parameter `
--name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 `
--region $REGION `
--query Parameter.Value `
--output text

$INSTANCE_ID = aws ec2 run-instances `
--image-id $AMI_ID `
--instance-type $EC2_TYPE `
--security-group-ids $SG_ID `
--iam-instance-profile Name=sre-agent-ec2-profile `
--user-data file://userdata.sh `
--tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$EC2_NAME}]" `
--region $REGION `
--query "Instances[0].InstanceId" `
--output text
```

Validate SSM and nginx:

```powershell
aws ssm describe-instance-information --region $REGION

aws ssm send-command `
--instance-ids $INSTANCE_ID `
--document-name AWS-RunShellScript `
--parameters commands="systemctl is-active nginx" `
--region $REGION
```

# 12. Lambda1 portability and deployment

Lambda1 must not hardcode an instance ID:

```python
TARGET_INSTANCE_ID = os.environ.get("TARGET_INSTANCE_ID", "")
# ...
"instance_id": TARGET_INSTANCE_ID,
```

Package and create:

```powershell
Set-Location .\lambda
Compress-Archive -Path .\lambda_alert_parser.py `
-DestinationPath .\lambda_alert_parser.zip -Force

aws lambda create-function `
--function-name $LAMBDA1 `
--runtime python3.12 `
--role $LAMBDA_ROLE_ARN `
--handler lambda_alert_parser.lambda_handler `
--zip-file fileb://lambda_alert_parser.zip `
--timeout 60 `
--memory-size 256 `
--region $REGION
```

Configure:

```powershell
aws lambda update-function-configuration `
--function-name $LAMBDA1 `
--environment "Variables={ORCHESTRATOR_QUEUE_URL=$QUEUE_URL,TARGET_INSTANCE_ID=$INSTANCE_ID}" `
--region $REGION
```

# 13. Lambda2 deployment

```powershell
Compress-Archive -Path .\lambda_bedrock_orchestrator.py `
-DestinationPath .\lambda_bedrock_orchestrator.zip -Force

aws lambda create-function `
--function-name $LAMBDA2 `
--runtime python3.12 `
--role $LAMBDA_ROLE_ARN `
--handler lambda_bedrock_orchestrator.lambda_handler `
--zip-file fileb://lambda_bedrock_orchestrator.zip `
--timeout 300 `
--memory-size 512 `
--region $REGION

aws lambda update-function-configuration `
--function-name $LAMBDA2 `
--environment "Variables={S3_BUCKET=$BUCKET,GOOGLE_SECRET_NAME=$GEMINI_SECRET,REQUIRE_LLM=true,GEMINI_MODEL=$GEMINI_MODEL,APPROVAL_TABLE=$APPROVAL_TABLE,CIRCUIT_BREAKER_TABLE=$CIRCUIT_TABLE,P1_SNS_TOPIC_ARN=$SNS_ARN}" `
--region $REGION
```

Create trigger:

```powershell
aws lambda create-event-source-mapping `
--function-name $LAMBDA2 `
--event-source-arn $QUEUE_ARN `
--batch-size 1 `
--region $REGION
```

# 14. Lambda1 Function URL

Datadog uses **Lambda1 only**. Lambda2 is triggered by SQS.

```powershell
$FUNCTION_URL = aws lambda create-function-url-config `
--function-name $LAMBDA1 `
--auth-type NONE `
--region $REGION `
--query FunctionUrl `
--output text

aws lambda add-permission `
--function-name $LAMBDA1 `
--statement-id FunctionURLAllowPublicAccess `
--action lambda:InvokeFunctionUrl `
--principal "*" `
--function-url-auth-type NONE `
--region $REGION

aws lambda add-permission `
--function-name $LAMBDA1 `
--statement-id AllowPublicInvokeFunction `
--action lambda:InvokeFunction `
--principal "*" `
--region $REGION
```

In this validated environment, the URL returned `Forbidden` until the second permission was added.

# 15. Datadog

Install the Linux Agent through SSM using the onboarding-generated key. Use a JSON file to avoid PowerShell quoting problems:

```json
{
  "commands": [
    "export DD_API_KEY=<ROTATED_DATADOG_API_KEY>",
    "export DD_SITE=datadoghq.com",
    "curl -L https://install.datadoghq.com/scripts/install_script_agent7.sh -o /tmp/dd-install.sh",
    "bash /tmp/dd-install.sh"
  ]
}
```

```powershell
aws ssm send-command `
--instance-ids $INSTANCE_ID `
--document-name AWS-RunShellScript `
--parameters file://datadog-install.json `
--region $REGION
```

Webhook:

```text
Name: sre-agent-webhook
URL: <LAMBDA1_FUNCTION_URL>
Monitor notification: @webhook-sre-agent-webhook
```

Use dynamic Datadog variables in the final webhook payload, not temporary CPU/memory/service constants:

```json
{
  "source": "datadog",
  "alert_id": "$ALERT_ID",
  "event": "$ALERT_TITLE",
  "host": "$HOSTNAME",
  "metric": "$ALERT_METRIC",
  "severity": "$ALERT_PRIORITY",
  "transition": "$ALERT_TRANSITION",
  "status": "$ALERT_STATUS"
}
```

# 16. End-to-end test matrix

## CPU P3

```powershell
aws ssm send-command `
--instance-ids $INSTANCE_ID `
--document-name AWS-RunShellScript `
--parameters commands="stress-ng --cpu 2 --timeout 300s" `
--region $REGION
```

Expected: Gemini `cpu_autoheal`, guardrail passed, SSM Success, `CPU_AUTOHEAL_DONE`, RCA `REMEDIATION_COMPLETED`.

## Memory P2

```powershell
aws ssm send-command `
--instance-ids $INSTANCE_ID `
--document-name AWS-RunShellScript `
--parameters commands="stress-ng --vm 1 --vm-bytes 70% --timeout 300s" `
--region $REGION

aws dynamodb scan `
--table-name $APPROVAL_TABLE `
--region $REGION
```

Expected: `PENDING_APPROVAL`; no Gemini and no SSM remediation after severity routing.

## Disk P1

Use a controlled threshold on a disposable instance. Do not fill the root filesystem to 100%.

Expected: SNS escalation, RCA `ESCALATED`, no Gemini and no auto-heal.

## Service P4

```powershell
aws ssm send-command `
--instance-ids $INSTANCE_ID `
--document-name AWS-RunShellScript `
--parameters commands="systemctl stop nginx" `
--region $REGION
```

Expected: Gemini `service_autoheal`, SSM stdout `active`, RCA `REMEDIATION_COMPLETED`.

# 17. Evidence and operational checks

```powershell
aws logs tail "/aws/lambda/$LAMBDA1" --since 10m --region $REGION
aws logs tail "/aws/lambda/$LAMBDA2" --since 10m --region $REGION

aws s3 ls "s3://$BUCKET/rca/" --recursive --region $REGION

aws dynamodb scan --table-name $APPROVAL_TABLE --region $REGION
aws dynamodb scan --table-name $CIRCUIT_TABLE --region $REGION
```

Reset a circuit-breaker key for a controlled retest:

```powershell
@'
{
  "incident_id": {
    "S": "ec2-test_system.cpu.idle"
  }
}
'@ | Set-Content -Encoding ASCII .\delete-key.json

aws dynamodb delete-item `
--table-name $CIRCUIT_TABLE `
--key file://delete-key.json `
--region $REGION
```

# 18. Troubleshooting lessons

| Symptom | Root cause | Fix |
|---|---|---|
| Lambda ZIP path not found | Already inside `lambda` folder | Remove duplicate `lambda\` prefix |
| SQS trigger rejected | Visibility timeout lower than Lambda timeout | Set queue to 360 seconds |
| Lambda log group absent | Function never invoked | Invoke once; logs are auto-created |
| Function URL `Forbidden` | Missing public invocation permission | Add both permission statements and retest |
| `NoSuchKey` | Runbooks not under `runbooks/` | Upload and list exact keys |
| RCA `AccessDenied` | Missing `s3:PutObject` | Add permission and reapply policy |
| Secret `AccessDenied` | Missing `GetSecretValue` | Add permission and reapply policy |
| Gemini 404 | Unsupported model | List models and set a valid model |
| SSM `InvalidInstanceId` | Old hardcoded ID | Use `TARGET_INSTANCE_ID` and redeploy Lambda1 |
| Circuit breaker open | Two failed attempts | Delete exact incident key for retest |
| No new webhook | Monitor did not transition | Force OK → ALERT |
| Inline JSON errors | PowerShell quoting | Use `file://` JSON files |

# 19. GitHub publication

Never commit:

```text
.env
*.zip
__pycache__/
AWS credentials
Datadog/Gemini API keys
private keys
presigned URLs
incident-history/
unredacted screenshots
```

Review and push:

```powershell
git status --short
git diff --cached

git add README.md .gitignore architecture docs iam lambda runbooks
git status

git commit -m "Add validated multi-region deployment guide and portable Lambda configuration"
git push origin main

git tag -a v2.0-us-east-2-validated -m "Validated P1 P2 P3 P4 workflows in us-east-2"
git push origin v2.0-us-east-2-validated
```
