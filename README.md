# AI-Powered Self-Healing SRE Agent

AI-assisted infrastructure remediation platform integrating Datadog, AWS Lambda, Amazon SQS, Gemini, S3 runbooks, execution guardrails, DynamoDB circuit breaker, AWS Systems Manager, SNS escalation, approval workflow, and RCA storage.

# AI-Powered Self-Healing SRE Agent

AI-assisted infrastructure remediation platform integrating Datadog, AWS Lambda, Amazon SQS, Gemini, S3 runbooks, execution guardrails, DynamoDB circuit breaker, AWS Systems Manager, SNS escalation, approval workflow, and RCA storage.

---

# Solution Architecture

docs/screenshots/01-architecture.png

---

# Validation Evidence

## CPU Auto-Heal (P3)

!ocs/screenshots/03-cpu-autoheal-success.png

Validated:

- Gemini decision = cpu_autoheal
- Guardrail passed
- SSM successful
- CPU_AUTOHEAL_DONE

---

## Memory Approval Workflow (P2)

![Memory](docs/screenshots/04nding-approval.png

Validated:

- Approval Request Generated
- DynamoDB PENDING_APPROVAL

---

## Service Auto-Heal (P4)

![Service](docs/screenshots/remediation-completed.png

Validated:

- Gemini decision = service_autoheal
- Nginx restarted
- RCA generated

---

## RCA Evidence

docs/screenshots/06-rca.png

---

## Gemini Decision Evidence

docs/screenshots/08-gemini-decision.png

---

# Validated Workflows

## Validated Workflows

- P1: Human escalation through Amazon SNS with RCA
- P2: Approval request stored in DynamoDB with RCA
- P3: AI-assisted auto-remediation with guardrails and SSM
- P4: AI-assisted service recovery and verification

## Validated Scenarios

- CPU spike remediation
- Memory pressure remediation
- Disk utilization workflow
- Nginx service recovery
- Dangerous command guardrail rejection
- Circuit breaker protection
- RCA generation and storage

## Repository Structure

- lambda/ - Lambda1 alert parser and Lambda2 orchestrator
- 
unbooks/ - Approved remediation runbooks
- iam/ - Example least-privilege IAM policies
- rchitecture/ - Architecture and service documentation
- slo-definitions/ - SLO definitions
- docs/ - Deployment and workshop documentation

## Security

Never commit API keys, AWS credentials, private keys, presigned URLs, personal information, customer information, or production incident data.

## Deployment

See docs/AI_Powered_Self_Healing_SRE_Platform_Deployment_Guide.docx.
