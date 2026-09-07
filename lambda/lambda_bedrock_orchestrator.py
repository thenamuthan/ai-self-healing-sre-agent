import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError


logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")
CIRCUIT_TABLE = os.environ.get("CIRCUIT_BREAKER_TABLE", "sre-agent-circuit-breaker")
APPROVAL_TABLE = os.environ.get("APPROVAL_TABLE", "sre-agent-approval-requests")
S3_BUCKET = os.environ.get("S3_BUCKET", "sre-agent-runbooks-564711065576")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "")
GOOGLE_SECRET_NAME = os.environ.get("GOOGLE_SECRET_NAME", "sre-agent/google-api-key")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
REQUIRE_LLM = os.environ.get("REQUIRE_LLM", "true").lower() == "true"
P1_SNS_TOPIC_ARN = os.environ.get("P1_SNS_TOPIC_ARN", "")

ssm = boto3.client("ssm", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)
secretsmanager = boto3.client("secretsmanager", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
circuit_table = dynamodb.Table(CIRCUIT_TABLE)
approval_table = dynamodb.Table(APPROVAL_TABLE)

SYSTEM_PROMPT = """
You are an expert SRE AI agent.
Analyze the Datadog alert and the approved S3 runbook summary.

Return ONLY one valid JSON object.
Do not include markdown, commentary, shell commands, or additional text.

Choose exactly one remediation_key:
- cpu_autoheal
- memory_autoheal
- disk_autoheal
- service_autoheal
- escalate

Return this structure:
{"remediation_key":"memory_autoheal","confidence":"high","reason":"brief reason","escalate":false}
""".strip()

CPU_AUTOHEAL_COMMAND = "pkill -f 'stress|stress-ng|yes' || true; echo CPU_AUTOHEAL_DONE"
MEMORY_AUTOHEAL_COMMAND = "sync; echo 3 > /proc/sys/vm/drop_caches; echo MEMORY_AUTOHEAL_DONE"
DISK_AUTOHEAL_COMMAND = "find /var/log -name '*.gz' -mtime +7 -delete; find /tmp -mtime +3 -type f -delete; echo DISK_AUTOHEAL_DONE"
SERVICE_AUTOHEAL_COMMAND = "systemctl restart nginx; systemctl is-active nginx"
TEST_COMMAND = "echo AUTOHEAL_TEST_SUCCESS"

APPROVED_ACTIONS = {
    "cpu_autoheal": CPU_AUTOHEAL_COMMAND,
    "memory_autoheal": MEMORY_AUTOHEAL_COMMAND,
    "disk_autoheal": DISK_AUTOHEAL_COMMAND,
    "service_autoheal": SERVICE_AUTOHEAL_COMMAND,
    "autoheal_test": TEST_COMMAND,
}
APPROVED_COMMANDS = set(APPROVED_ACTIONS.values())

BLOCKED_COMMANDS = [
    "rm -rf",
    "shutdown",
    "reboot",
    "mkfs",
    "fdisk",
    "userdel",
    "passwd",
    "iptables -f",
    "chmod 777 /",
    "curl | bash",
    "wget | bash",
    ":(){",
    "dd if=",
    "init 0",
    "init 6",
    "kill -9 $(ps aux --sort=-%cpu",
    "awk 'nr==2{print $2}'",
]

RUNBOOK_KEYS = {
    "cpu": "runbooks/cpu-spike-runbook.md",
    "memory": "runbooks/memory-leak-runbook.md",
    "mem": "runbooks/memory-leak-runbook.md",
    "disk": "runbooks/disk-full-runbook.md",
    "service": "runbooks/service-down-runbook.md",
    "health": "runbooks/service-down-runbook.md",
}

TERMINAL_SSM_STATES = {
    "Success",
    "Cancelled",
    "Failed",
    "TimedOut",
    "Cancelling",
}


def get_google_api_key():
    try:
        response = secretsmanager.get_secret_value(SecretId=GOOGLE_SECRET_NAME)
        secret = response.get("SecretString", "")
        if not secret:
            raise ValueError("SecretString is empty")
        return secret
    except Exception as exc:
        logger.error("Failed to get Google API key: %s", exc)
        return ""


def get_runbook(metric):
    metric_lower = str(metric or "").lower()
    for keyword, key in RUNBOOK_KEYS.items():
        if keyword in metric_lower:
            try:
                response = s3.get_object(Bucket=S3_BUCKET, Key=key)
                content = response["Body"].read().decode("utf-8")
                logger.info("Runbook loaded: %s", key)
                return content[:4000], key
            except Exception as exc:
                logger.error("S3 runbook read failed for %s: %s", key, exc)
                return "", key

    logger.warning("No matching runbook for metric: %s", metric)
    return "", ""


def extract_json(text):
    clean_text = str(text or "").strip()
    clean_text = clean_text.replace("```json", "").replace("```", "").strip()
    start = clean_text.find("{")
    end = clean_text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in Gemini response")
    return json.loads(clean_text[start:end])


def call_gemini(alert, runbook):
    api_key = get_google_api_key()
    if not api_key:
        raise ValueError("Google API key not found")

    prompt = f"""
{SYSTEM_PROMPT}

Alert details:
- Alert name: {alert.get('alert_name', 'unknown')}
- Host: {alert.get('host', 'unknown')}
- Instance ID: {alert.get('instance_id', 'unknown')}
- Metric: {alert.get('metric', 'unknown')}
- Severity: {alert.get('severity', 'P3')}
- Value: {alert.get('value', 'unknown')}

Approved runbook summary:
{runbook[:1200]}
""".strip()

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "topP": 0.1,
            "topK": 1,
            "maxOutputTokens": 1024,
        },
    }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={api_key}"
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            api_result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini HTTP {exc.code}: {body[:500]}") from exc

    logger.info("Gemini response received from model %s", GEMINI_MODEL)
    candidates = api_result.get("candidates", [])
    if not candidates:
        raise ValueError(f"Gemini returned no candidates: {json.dumps(api_result)[:500]}")

    parts = candidates[0].get("content", {}).get("parts", [])
    raw = " ".join(
        part.get("text", "")
        for part in parts
        if part.get("text", "").strip()
    )
    logger.info("Gemini text: %s", raw[:1000])
    return extract_json(raw)


def build_action_from_llm(alert, llm_result):
    remediation_key = str(llm_result.get("remediation_key", "escalate"))
    instance_id = alert.get("instance_id", "")
    confidence = str(llm_result.get("confidence", "low")).lower()
    reason = llm_result.get("reason", "LLM decision")
    requested_escalation = bool(llm_result.get("escalate", False))

    if remediation_key == "escalate" or requested_escalation:
        return {
            "action": "escalate",
            "command": "",
            "instance_id": instance_id,
            "confidence": confidence,
            "reason": reason,
            "escalate": True,
        }

    command = APPROVED_ACTIONS.get(remediation_key, "")
    if not command:
        return {
            "action": "escalate",
            "command": "",
            "instance_id": instance_id,
            "confidence": "low",
            "reason": f"Unknown remediation_key from LLM: {remediation_key}",
            "escalate": True,
        }

    return {
        "action": remediation_key,
        "command": command,
        "instance_id": instance_id,
        "confidence": confidence,
        "reason": reason,
        "escalate": False,
    }


def choose_runbook_command(alert):
    metric = str(alert.get("metric", "")).lower()
    if "cpu" in metric:
        key = "cpu_autoheal"
    elif "memory" in metric or "mem" in metric:
        key = "memory_autoheal"
    elif "disk" in metric:
        key = "disk_autoheal"
    elif "service" in metric or "health" in metric:
        key = "service_autoheal"
    else:
        return {
            "action": "escalate",
            "command": "",
            "instance_id": alert.get("instance_id", ""),
            "confidence": "low",
            "reason": "Unknown metric; no approved action exists",
            "escalate": True,
        }

    return {
        "action": key,
        "command": APPROVED_ACTIONS[key],
        "instance_id": alert.get("instance_id", ""),
        "confidence": "high",
        "reason": f"Approved fallback action selected for metric {metric}",
        "escalate": False,
    }


def ask_llm(alert, runbook):
    try:
        logger.info("Calling Gemini API")
        llm_result = call_gemini(alert, runbook)
        logger.info("Gemini decision: %s", json.dumps(llm_result))
        action = build_action_from_llm(alert, llm_result)
        logger.info("Mapped action: %s", json.dumps(action))
        return action
    except Exception as exc:
        logger.error("Gemini failed: %s", exc)
        if REQUIRE_LLM:
            return {
                "action": "escalate",
                "command": "",
                "instance_id": alert.get("instance_id", ""),
                "confidence": "low",
                "reason": f"Gemini unavailable or invalid: {exc}",
                "escalate": True,
            }
        logger.warning("REQUIRE_LLM=false; using approved fallback action")
        return choose_runbook_command(alert)


def validate_command(command):
    if not command:
        logger.error("GUARDRAIL BLOCKED: empty command")
        return False

    lowered = command.lower().strip()
    for blocked in BLOCKED_COMMANDS:
        if blocked in lowered:
            logger.error("GUARDRAIL BLOCKED DANGEROUS COMMAND: %s", command)
            return False

    if command not in APPROVED_COMMANDS:
        logger.error("GUARDRAIL BLOCKED NON-APPROVED COMMAND: %s", command)
        return False

    logger.info("GUARDRAIL PASSED COMMAND: %s", command)
    return True


def check_circuit_breaker(incident_id):
    try:
        response = circuit_table.get_item(Key={"incident_id": incident_id})
        attempts = int(response.get("Item", {}).get("attempts", 0))
        logger.info("Circuit breaker attempts for %s: %s", incident_id, attempts)
        if attempts >= 2:
            logger.warning("Circuit breaker OPEN for %s", incident_id)
            return False, attempts
        return True, attempts
    except Exception as exc:
        logger.error("Circuit breaker read error: %s", exc)
        return True, 0


def update_circuit_breaker(incident_id, success):
    try:
        if success:
            circuit_table.delete_item(Key={"incident_id": incident_id})
        else:
            circuit_table.update_item(
                Key={"incident_id": incident_id},
                UpdateExpression=(
                    "SET attempts = if_not_exists(attempts, :zero) + :one, "
                    "updated_at = :updated_at"
                ),
                ExpressionAttributeValues={
                    ":zero": 0,
                    ":one": 1,
                    ":updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    except Exception as exc:
        logger.error("Circuit breaker update error: %s", exc)


def send_p1_escalation(alert):
    if not P1_SNS_TOPIC_ARN:
        logger.error("P1 SNS topic ARN is not configured")
        return False

    subject = f"[P1 ESCALATION] {alert.get('alert_name', 'Unknown Alert')}"
    message = {
        "severity": str(alert.get("severity", "P1")).upper(),
        "alert_name": alert.get("alert_name", "Unknown Alert"),
        "metric": alert.get("metric", "unknown"),
        "value": alert.get("value", "unknown"),
        "host": alert.get("host", "unknown"),
        "instance_id": alert.get("instance_id", "unknown"),
        "decision": "ESCALATE",
        "automated_remediation": "NOT_EXECUTED",
        "required_action": "Engage the on-call SRE or incident commander",
    }

    try:
        response = sns.publish(
            TopicArn=P1_SNS_TOPIC_ARN,
            Subject=subject[:100],
            Message=json.dumps(message, indent=2),
        )
        logger.info("P1 escalation sent. MessageId=%s", response.get("MessageId"))
        return True
    except Exception as exc:
        logger.error("P1 escalation failed: %s", exc)
        return False


def save_approval_request(alert):
    request_id = f"REQ-{int(time.time())}"
    now = datetime.now(timezone.utc).isoformat()
    approval_table.put_item(
        Item={
            "request_id": request_id,
            "status": "PENDING_APPROVAL",
            "severity": "P2",
            "metric": alert.get("metric", "unknown"),
            "instance_id": alert.get("instance_id", ""),
            "host": alert.get("host", "unknown"),
            "alert_name": alert.get("alert_name", "Unknown Alert"),
            "value": str(alert.get("value", "unknown")),
            "created_time": now,
            "updated_time": now,
        }
    )
    logger.info("P2 approval request stored: %s", request_id)
    return request_id


def generate_rca(alert, action, result, workflow_status, request_id="", runbook_key=""):
    try:
        severity = str(alert.get("severity", "P3")).upper()
        metric = str(alert.get("metric", "unknown")).lower()
        timestamp = int(time.time())
        key = f"rca/rca-{severity.lower()}-{metric}-{timestamp}.json"

        rca = {
            "incident": alert.get("alert_name", "Unknown Incident"),
            "severity": severity,
            "metric": metric,
            "host": alert.get("host", "unknown"),
            "instance_id": alert.get("instance_id", "unknown"),
            "workflow_status": workflow_status,
            "request_id": request_id,
            "detection_source": "Datadog",
            "llm_model": GEMINI_MODEL,
            "runbook_used": runbook_key,
            "action_taken": action.get("action", "unknown"),
            "command": action.get("command", ""),
            "execution_status": result.get("status", "NOT_EXECUTED"),
            "success": bool(result.get("success", False)),
            "verification": result.get("output", ""),
            "error": result.get("error", ""),
            "recommendation": (
                "Review recurring patterns, monitor thresholds, application behavior, "
                "and the approved remediation runbook."
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        s3.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(rca, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info("RCA saved to S3: %s", key)
        logger.info("RCA workflow status: %s", workflow_status)
        return key
    except Exception as exc:
        logger.error("RCA generation failed: %s", exc)
        return ""


def execute_ssm(instance_id, command):
    try:
        logger.info("SSM execution started on %s", instance_id)
        logger.info("Command: %s", command)
        response = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [command]},
            TimeoutSeconds=90,
        )
        command_id = response["Command"]["CommandId"]
        logger.info("SSM command id: %s", command_id)

        result = None
        for _ in range(18):
            try:
                result = ssm.get_command_invocation(
                    CommandId=command_id,
                    InstanceId=instance_id,
                )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") == "InvocationDoesNotExist":
                    time.sleep(3)
                    continue
                raise

            status = result.get("Status", "Unknown")
            if status in TERMINAL_SSM_STATES:
                break
            time.sleep(3)

        if result is None:
            return {
                "success": False,
                "status": "InvocationNotFound",
                "output": "",
                "error": "SSM invocation was not available before polling ended",
            }

        status = result.get("Status", "Unknown")
        output = result.get("StandardOutputContent", "")
        error = result.get("StandardErrorContent", "")
        logger.info("SSM status: %s", status)
        logger.info("SSM stdout: %s", output)
        logger.info("SSM stderr: %s", error)
        return {
            "success": status == "Success",
            "status": status,
            "output": output,
            "error": error,
        }
    except Exception as exc:
        logger.error("SSM error: %s", exc)
        return {
            "success": False,
            "status": "Exception",
            "output": "",
            "error": str(exc),
        }


def send_slack(alert, action, result):
    if not SLACK_WEBHOOK or SLACK_WEBHOOK == "placeholder":
        return

    payload = {
        "text": (
            f"SRE Agent result: alert={alert.get('alert_name', '')}, "
            f"action={action.get('action', '')}, success={result.get('success', False)}"
        )
    }
    try:
        request = urllib.request.Request(
            SLACK_WEBHOOK,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(request, timeout=10)
    except Exception as exc:
        logger.error("Slack notification failed: %s", exc)


def lambda_handler(event, context):
    logger.info("Orchestrator started - LLM Decision + Guardrail Mode")
    logger.info("GEMINI_MODEL=%s", GEMINI_MODEL)
    logger.info("REQUIRE_LLM=%s", REQUIRE_LLM)
    logger.info("Incoming event: %s", json.dumps(event)[:2000])

    for record in event.get("Records", []):
        try:
            alert = json.loads(record["body"])
            logger.info(
                f"FULL ALERT JSON = {json.dumps(alert)}"
            )
            logger.info(
                f"METRIC RECEIVED = {alert.get('metric')}"
            )

            logger.info(
                f"SEVERITY RECEIVED = {alert.get('severity')}"
            )
            logger.info("Alert received from SQS: %s", json.dumps(alert))

            host = alert.get("host", "unknown")
            metric = str(alert.get("metric", "unknown")).lower()
            instance_id = alert.get("instance_id", "")
            severity = str(alert.get("severity", "P3")).upper()
            logger.info("Incident severity: %s", severity)

            if severity == "P1":
                logger.warning(
                    "P1 Incident detected. Auto-heal disabled. Escalating to on-call."
                )
                notification_sent = send_p1_escalation(alert)
                if notification_sent:
                    verification = (
                        "P1 escalation notification was published through Amazon SNS. "
                        "Automated remediation was not executed."
                    )
                    status = "NOT_EXECUTED"
                else:
                    verification = (
                        "P1 escalation notification delivery failed. "
                        "Automated remediation was not executed."
                    )
                    status = "NOTIFICATION_FAILED"

                generate_rca(
                    alert=alert,
                    action={"action": "sns_escalation", "command": ""},
                    result={
                        "success": notification_sent,
                        "status": status,
                        "output": verification,
                        "error": "" if notification_sent else "SNS publish failed",
                    },
                    workflow_status="ESCALATED",
                )
                continue

            if severity == "P2":
                logger.warning("P2 incident detected. Approval required.")
                request_id = save_approval_request(alert)
                logger.info("Approval request created: %s", request_id)
                generate_rca(
                    alert=alert,
                    action={"action": "approval_request_created", "command": ""},
                    result={
                        "success": True,
                        "status": "PENDING_APPROVAL",
                        "output": (
                            f"P2 approval request {request_id} was stored in DynamoDB. "
                            "No remediation command was executed."
                        ),
                        "error": "",
                    },
                    workflow_status="PENDING_APPROVAL",
                    request_id=request_id,
                )
                continue

            incident_id = f"{host}_{metric}"
            can_proceed, attempts = check_circuit_breaker(incident_id)
            if not can_proceed:
                result = {
                    "success": False,
                    "status": "CIRCUIT_BREAKER_OPEN",
                    "output": f"Circuit breaker open after {attempts} attempts",
                    "error": "",
                }
                generate_rca(
                    alert=alert,
                    action={"action": "escalate", "command": ""},
                    result=result,
                    workflow_status="ESCALATED",
                )
                send_slack(alert, {"action": "escalate"}, result)
                continue

            runbook, runbook_key = get_runbook(metric)
            if not runbook:
                result = {
                    "success": False,
                    "status": "RUNBOOK_NOT_FOUND",
                    "output": "No approved runbook was found",
                    "error": "",
                }
                update_circuit_breaker(incident_id, False)
                generate_rca(
                    alert=alert,
                    action={"action": "escalate", "command": ""},
                    result=result,
                    workflow_status="ESCALATED",
                    runbook_key=runbook_key,
                )
                continue

            action = ask_llm(alert, runbook)
            logger.info("Final decision: %s", json.dumps(action))

            if action.get("escalate") or action.get("confidence") == "low":
                result = {
                    "success": False,
                    "status": "LLM_ESCALATED",
                    "output": action.get("reason", "Escalated by LLM"),
                    "error": "",
                }
                update_circuit_breaker(incident_id, False)
                generate_rca(
                    alert=alert,
                    action=action,
                    result=result,
                    workflow_status="ESCALATED",
                    runbook_key=runbook_key,
                )
                send_slack(alert, action, result)
                continue

            if not instance_id:
                result = {
                    "success": False,
                    "status": "INSTANCE_ID_MISSING",
                    "output": "No instance_id was supplied",
                    "error": "",
                }
                update_circuit_breaker(incident_id, False)
                generate_rca(
                    alert=alert,
                    action=action,
                    result=result,
                    workflow_status="REMEDIATION_FAILED",
                    runbook_key=runbook_key,
                )
                continue

            command = action.get("command", "")
            if not validate_command(command):
                result = {
                    "success": False,
                    "status": "GUARDRAIL_BLOCKED",
                    "output": "Command was blocked by the execution guardrail",
                    "error": command,
                }
                update_circuit_breaker(incident_id, False)
                generate_rca(
                    alert=alert,
                    action=action,
                    result=result,
                    workflow_status="BLOCKED",
                    runbook_key=runbook_key,
                )
                continue

            result = execute_ssm(instance_id, command)
            update_circuit_breaker(incident_id, result.get("success", False))
            workflow_status = (
                "REMEDIATION_COMPLETED"
                if result.get("success")
                else "REMEDIATION_FAILED"
            )
            generate_rca(
                alert=alert,
                action=action,
                result=result,
                workflow_status=workflow_status,
                runbook_key=runbook_key,
            )
            send_slack(alert, action, result)
            logger.info("Complete - success: %s", result.get("success"))

        except Exception as exc:
            logger.exception("Error processing record: %s", exc)
            raise

    return {"statusCode": 200, "body": "Done"}
