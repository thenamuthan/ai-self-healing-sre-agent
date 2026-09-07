# Service Catalogue

## Demo Application Servers

### sre-app-server-1
- Type: EC2 t3.micro
- Region: us-east-1
- Role: Primary web server
- Application: myapp port 8080
- Monitoring: Datadog Agent
- Tags: Environment=demo, ManagedBy=sre-agent

### sre-app-server-2
- Type: EC2 t3.micro
- Region: us-east-1
- Role: Secondary web server
- Application: myapp port 8080
- Monitoring: Datadog Agent
- Tags: Environment=demo, ManagedBy=sre-agent

## SRE Agent Components
- Lambda 1: sre-agent-alert-parser
- Lambda 2: sre-agent-bedrock-orchestrator
- Knowledge Base: Bedrock RAG on this S3 bucket
- Circuit Breaker: DynamoDB
- Queue: SQS with DLQ

## Last Updated
2026-08-10
