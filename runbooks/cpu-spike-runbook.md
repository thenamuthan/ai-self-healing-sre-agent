# CPU Spike Runbook

## Severity Levels
- CPU > 70% = Warning
- CPU > 80% = P3
- CPU > 90% = P2
- CPU > 95% = P1

## Automated Remediation Steps

### Step 1 - Check Top CPU Process
Command: ps aux --sort=-%cpu | head -10

### Step 2 - Kill High CPU Process
Command: kill -9 $(ps aux --sort=-%cpu | awk 'NR==2{print $2}')

### Step 3 - Restart Service
Command: systemctl restart myapp

### Step 4 - Verify CPU Normal
Command: top -bn1 | grep Cpu

## Escalation
- CPU stays above 80% after 2 attempts
- Unknown process causing spike
- Multiple services affected

## Escalation Path
L1 to L2 SRE to SRE Lead

## Last Updated
2026-08-10
