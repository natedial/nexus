# Scheduling Guide

This guide shows how to schedule the Research Dispatch script to run automatically.

## Option 1: Cron (macOS/Linux)

### Daily at 9 AM
```bash
# Make the schedule script executable
chmod +x schedule.sh

# Edit crontab
crontab -e

# Add this line (runs daily at 9:00 AM):
0 9 * * * /Users/ndial/dev/research-dispatch/schedule.sh

# Or with logging:
0 9 * * * /Users/ndial/dev/research-dispatch/schedule.sh >> /Users/ndial/dev/research-dispatch/cron.log 2>&1
```

### Other Cron Schedules

Weekly (Monday at 9 AM):
```
0 9 * * 1 /Users/ndial/dev/research-dispatch/schedule.sh
```

Twice daily (9 AM and 5 PM):
```
0 9,17 * * * /Users/ndial/dev/research-dispatch/schedule.sh
```

Every hour:
```
0 * * * * /Users/ndial/dev/research-dispatch/schedule.sh
```

### View Current Cron Jobs
```bash
crontab -l
```

### Remove Cron Job
```bash
crontab -e
# Delete the line, save and exit
```

## Option 2: launchd (macOS)

Create a launch agent for more reliable macOS scheduling:

```bash
# Create plist file
cat > ~/Library/LaunchAgents/com.researchdispatch.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.researchdispatch</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/ndial/dev/research-dispatch/schedule.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/ndial/dev/research-dispatch/logs/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/ndial/dev/research-dispatch/logs/stderr.log</string>
</dict>
</plist>
EOF

# Create logs directory
mkdir -p logs

# Load the agent
launchctl load ~/Library/LaunchAgents/com.researchdispatch.plist

# Start it immediately (optional)
launchctl start com.researchdispatch
```

### Manage launchd Job
```bash
# Check status
launchctl list | grep researchdispatch

# Unload (stop)
launchctl unload ~/Library/LaunchAgents/com.researchdispatch.plist

# Reload after changes
launchctl unload ~/Library/LaunchAgents/com.researchdispatch.plist
launchctl load ~/Library/LaunchAgents/com.researchdispatch.plist
```

## Option 3: systemd (Linux)

Create a systemd service and timer:

```bash
# Create service file
sudo nano /etc/systemd/system/research-dispatch.service
```

Add:
```ini
[Unit]
Description=Research Dispatch Report Generator
After=network.target

[Service]
Type=oneshot
User=ndial
WorkingDirectory=/Users/ndial/dev/research-dispatch
ExecStart=/Users/ndial/dev/research-dispatch/schedule.sh

[Install]
WantedBy=multi-user.target
```

Create timer:
```bash
sudo nano /etc/systemd/system/research-dispatch.timer
```

Add:
```ini
[Unit]
Description=Run Research Dispatch daily at 9 AM

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable research-dispatch.timer
sudo systemctl start research-dispatch.timer

# Check status
sudo systemctl status research-dispatch.timer
sudo systemctl list-timers
```

## Testing

Run manually to test:
```bash
cd /Users/ndial/dev/research-dispatch
./schedule.sh
```

Or directly:
```bash
cd /Users/ndial/dev/research-dispatch
source venv/bin/activate
python src/main.py
```
