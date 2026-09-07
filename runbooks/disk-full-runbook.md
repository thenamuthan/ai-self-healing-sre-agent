# Disk Full Runbook

## Severity Levels
- Disk > 75% = Warning
- Disk > 85% = P3
- Disk > 95% = P2
- Disk = 100% = P1

## Automated Remediation Steps

### Step 1 - Check Disk Usage
Command: df -h

### Step 2 - Find Large Directories
Command: du -sh /* 2>/dev/null | sort -rh | head -10

### Step 3 - Check Inode Usage
Command: df -i

### Step 4 - Clean Old Logs
Command: find /var/log -name "*.gz" -mtime +7 -delete

### Step 5 - Clean Temp Files
Command: find /tmp -mtime +3 -type f -delete

### Step 6 - Verify Disk Freed
Command: df -h

## Escalation
- Disk still above 85% after cleanup
- Database directory filling up
- No files to clean

## Escalation Path
L1 to L2 SRE to Infrastructure Team

## Last Updated
2026-08-10
