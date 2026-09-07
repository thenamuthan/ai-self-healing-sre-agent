# Memory Leak Runbook

## Severity Levels
- Memory > 75% = Warning
- Memory > 85% = P3
- Memory > 90% = P2
- OOMKiller active = P1

## Automated Remediation Steps

### Step 1 - Check Memory Usage
Command: free -h

### Step 2 - Find Top Memory Process
Command: ps aux --sort=-%mem | head -10

### Step 3 - Check OOM Killer
Command: dmesg | grep -i "killed process" | tail -10

### Step 4 - Clear Page Cache
Command: sync; echo 3 > /proc/sys/vm/drop_caches

### Step 5 - Restart Service
Command: systemctl restart myapp

### Step 6 - Verify Memory Normal
Command: free -h

## Escalation
- Memory stays above 85% after restart
- OOM killer actively killing processes
- Swap usage above 80%

## Escalation Path
L1 to L2 SRE to SRE Lead to Application Team

## Last Updated
2026-08-10
