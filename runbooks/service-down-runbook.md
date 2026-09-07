# Service Down Runbook

## Severity Levels
- Single instance down = P3
- All instances down = P2
- Core dependency down = P1

## Automated Remediation Steps

### Step 1 - Check Service Status
Command: systemctl status myapp

### Step 2 - Check Service Logs
Command: journalctl -u myapp -n 50 --no-pager

### Step 3 - Check Port Availability
Command: ss -tlnp | grep 8080

### Step 4 - Restart Service
Command: systemctl restart myapp

### Step 5 - Verify Service Running
Command: systemctl is-active myapp

### Step 6 - Test Health Endpoint
Command: curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/health

## Escalation
- Service fails after 2 restart attempts
- Service starts but health check fails
- Multiple services down simultaneously

## Escalation Path
L1 to L2 SRE to SRE Lead to Application Team

## Last Updated
2026-08-10
