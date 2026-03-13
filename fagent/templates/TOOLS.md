# TOOLS.md - Local Configuration

Skills define _how_ tools work. This file is for _your_ specifics—environment-unique details.

## What Goes Here

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- API endpoints
- Custom shortcuts
- Anything environment-specific

## Examples

### Cameras
- `living-room` → Main area, 180° wide angle
- `front-door` → Entrance, motion-triggered

### SSH Hosts
- `home-server` → 192.168.1.100, user: admin
- `work-dev` → dev.company.com, port 2222

### TTS Preferences
- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod

### Custom Aliases
- `deploy` → `./scripts/deploy.sh --env prod`
- `logs` → `tail -f /var/log/app.log`

## Tool-Specific Notes

### exec — Safety Limits

- Commands have configurable timeout (default 60s)
- Dangerous commands blocked: `rm -rf`, `format`, `dd`, `shutdown`, etc.
- Output truncated at 10,000 characters
- `restrictToWorkspace` config limits file access to workspace

### cron — Scheduled Reminders

Refer to cron skill for detailed usage patterns.

---

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means:
- Update skills without losing your notes
- Share skills without leaking infrastructure details
- Quick reference for environment-specific details

Add whatever helps you work efficiently. This is your cheat sheet.
