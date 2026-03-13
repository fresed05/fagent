# Skills System Documentation

## Overview

Skills are reusable knowledge modules that teach the agent how to perform specific tasks or use certain tools. Each skill is a markdown file with YAML frontmatter.

## Structure

```
fagent/fagent/skills/          # Builtin skills (shipped with fagent)
  ├── fagent/
  │   └── SKILL.md             # fagent architecture guide
  ├── github/
  │   └── SKILL.md             # GitHub CLI integration
  └── ...

~/.fagent/workspace/skills/    # User skills (workspace-specific)
  └── custom-skill/
      └── SKILL.md
```

## Skill Format

```markdown
---
name: skill-name
description: Brief description of what this skill does
always: true                   # Optional: always load this skill
metadata: |                    # Optional: fagent-specific metadata
  {
    "requires": {
      "bins": ["gh"],          # Required CLI tools
      "env": ["GITHUB_TOKEN"]  # Required environment variables
    }
  }
---

# Skill Content

Markdown content that teaches the agent...
```

## Priority

1. **Workspace skills** (`~/.fagent/workspace/skills/`) - highest priority
2. **Builtin skills** (`fagent/fagent/skills/`) - fallback

Workspace skills override builtin skills with the same name.

## CLI Commands

### View available skills
```bash
fagent skills
```

Shows all available skills with:
- Name
- Description
- Source (builtin/workspace)
- Status (✓ available / ✗ missing requirements)

### Initialize workspace with builtin skills
```bash
fagent onboard
```

Copies builtin skills to workspace if they don't exist.

## Usage in Agent

Skills are automatically loaded by `SkillsLoader`:

```python
from fagent.agent.skills import SkillsLoader

loader = SkillsLoader(workspace)

# List all skills
skills = loader.list_skills()

# Load specific skill
content = loader.load_skill("fagent")

# Get skills summary for agent context
summary = loader.build_skills_summary()
```

## Creating Custom Skills

1. Create directory in workspace: `~/.fagent/workspace/skills/my-skill/`
2. Create `SKILL.md` with frontmatter
3. Add skill content in markdown
4. Skill will be automatically discovered

## Built-in Skills

- **fagent** - Architecture and memory system guide
- **github** - GitHub CLI integration
- **cron** - Schedule reminders and tasks
- **weather** - Weather forecasts
- **clawhub** - Search and install skills from ClawHub
- **skill-creator** - Create new skills
- **agent-management** - Manage agent instances
- **summarize** - Summarize URLs and transcripts
- **tmux** - Remote-control tmux sessions

## Implementation Details

**Files**:
- `fagent/agent/skills.py` - SkillsLoader class
- `fagent/utils/helpers.py` - sync_workspace_templates() for onboarding
- `fagent/cli/commands.py` - CLI commands

**Key Methods**:
- `list_skills()` - List all available skills
- `load_skill(name)` - Load skill content
- `build_skills_summary()` - XML summary for agent context
- `get_always_skills()` - Get skills marked as always=true
