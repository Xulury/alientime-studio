# Hermes skills for the Alien Time Listing Studio

Each folder holds one skill (`SKILL.md`). The skills only tell Hermes **which studio command to run and
what to check in its JSON output**. All logic, safety gates and permissions live in the studio, which
Hermes reaches through `studio-agent` (or `python -m app.hermes.cli`) with a scoped agent token.

Install: link this folder into Hermes' skills directory, e.g.

    ln -s /path/to/alien-time-listing-studio/skills ~/.hermes/skills/alientime

Environment for the Hermes process (inject from your password manager, never commit):

    STUDIO_API_URL=http://127.0.0.1:8000
    STUDIO_AGENT_TOKEN=at_...        # Settings → Agent access → New token

Hermes may improve its own skills. Keep this folder in git and merge changes only after reading the
diff — especially anything touching serial safety, claims or publishing.
