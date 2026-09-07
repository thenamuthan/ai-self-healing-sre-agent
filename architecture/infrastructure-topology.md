# Infrastructure Topology

## Flow Description
1. Datadog fires alert
2. EventBridge receives webhook
3. SQS queue holds alert safely
4. Lambda 1 parses alert details
5. Lambda 2 calls Bedrock Claude
6. Claude reads runbooks from S3 via RAG
7. Claude decides remediation action
8. DynamoDB checks circuit breaker
9. SSM executes command on EC2
10. Datadog Synthetic verifies fix
11. Alert auto-closed via Datadog Events API
12. Slack notification sent

## AWS Resources
- EC2: sre-app-server-1 and sre-app-server-2
- Lambda: sre-agent-alert-parser
- Lambda: sre-agent-bedrock-orchestrator
- SQS: sre-agent-queue
- SQS: sre-agent-dlq
- DynamoDB: sre-agent-circuit-breaker
- S3: sre-agent-runbooks bucket
- EventBridge: sre-agent-datadog-alerts
- IAM Role: sre-agent-lambda-role

## Last Updated
2026-08-10
