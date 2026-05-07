# Workflow driver

`dpti workflow` provides a lightweight command-line workflow driver for chaining
existing `dpti` commands.  It is intended for long thermodynamic-integration
campaigns where the user wants one JSON file to describe the ordered calculation
steps, while `dpti` records which steps have completed and where to resume.

The workflow driver does not replace the existing physics modules.  Each step is
still an ordinary `dpti equi`, `dpti hti`, `dpti ti`, or `dpti gdi` command.  The
driver adds orchestration, state tracking, output checks, and restart support.

## Minimal schema

```json
{
  "work_base": ".",
  "state_file": "workflow_state.json",
  "steps": [
    {
      "name": "npt.gen",
      "command": ["dpti", "equi", "gen", "npt.json", "-o", "npt"],
      "done_if": ["npt/in.lammps"]
    },
    {
      "name": "npt.run",
      "command": ["dpti", "equi", "run", "npt", "machine.json"],
      "done_if": ["npt/out.lmp", "npt/log.lammps"]
    },
    {
      "name": "npt.compute",
      "command": ["dpti", "equi", "compute", "npt"],
      "done_if": ["npt/result.json"]
    },
    {
      "name": "nvt.gen",
      "command": ["dpti", "equi", "gen", "nvt.json", "-o", "nvt", "--conf-npt", "npt"],
      "done_if": ["nvt/in.lammps"]
    },
    {
      "name": "hti.gen",
      "command": ["dpti", "hti", "gen", "hti.json", "-o", "hti", "-s", "one-step"],
      "done_if": ["hti/in.json"]
    }
  ]
}
```

`command` may be either a list of command-line tokens or a shell-like string.
When the first token is `dpti`, the driver executes the current Python
environment's `dpti.main` module.  This makes development checkouts behave the
same way as installed command-line environments.

`done_if` lists files or directories that must exist for a step to be considered
complete.  When a completed step is encountered again, it is skipped unless
`--rerun-all` is used.

## Commands

```bash
dpti workflow run workflow.json
dpti workflow status workflow.json
dpti workflow resume workflow.json
dpti workflow run workflow.json --from-step hti.gen
dpti workflow run workflow.json --rerun-all
dpti workflow run workflow.json --dry-run
```

The workflow state is stored in `workflow_state.json` by default.  If a run is
interrupted, rerunning `dpti workflow resume workflow.json` continues from the
saved state and verifies the `done_if` outputs before skipping completed steps.
