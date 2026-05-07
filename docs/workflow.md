# Workflow driver

`dpti workflow` provides a lightweight command-line workflow driver for chaining
existing `dpti` commands.  It is intended for long thermodynamic-integration
campaigns where the user wants one JSON file to describe the ordered calculation
steps, while `dpti` records which steps have completed and where to continue.

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
      "needs": [],
      "command": ["dpti", "equi", "gen", "npt.json", "-o", "npt"],
      "done_if": ["npt/in.lammps"]
    },
    {
      "name": "npt.run",
      "needs": ["npt.gen"],
      "command": ["dpti", "equi", "run", "npt", "machine.json"],
      "done_if": ["npt/out.lmp", "npt/log.lammps"]
    },
    {
      "name": "npt.compute",
      "needs": ["npt.run"],
      "command": ["dpti", "equi", "compute", "npt"],
      "done_if": ["npt/result.json"]
    },
    {
      "name": "nvt.gen",
      "needs": ["npt.compute"],
      "command": ["dpti", "equi", "gen", "nvt.json", "-o", "nvt", "--conf-npt", "npt"],
      "done_if": ["nvt/in.lammps"]
    },
    {
      "name": "hti.gen",
      "needs": ["nvt.run"],
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

For multi-task jobs, `done_if` may contain glob patterns such as
`hti/task.*/log.lammps` or `ti.t/task.*/log.lammps`.  If the parent path contains
a glob, the driver checks that every matching task directory contains the
requested output file.  This avoids marking an HTI or TI run as complete when
only one LAMMPS task has finished.

Use `needs` to describe the dependency graph and allow independent steps to run
together.  A root step should set `"needs": []`.  For example, `tti.run` and
`pti.run` can depend on their own `gen` steps, while their `compute` steps can
depend on both the TI run and the HTI compute step.

```json
{
  "name": "tti.gen",
  "needs": ["nvt.run"],
  "command": ["dpti", "ti", "gen", "ti.t.json", "-o", "ti.t"],
  "done_if": ["ti.t/ti_settings.json"]
},
{
  "name": "tti.run",
  "command": ["dpti", "ti", "run", "ti.t", "machine.json"],
  "done_if": ["ti.t/task.*/log.lammps"]
},
{
  "name": "tti.compute",
  "needs": ["tti.run", "hti.compute"],
  "command": ["dpti", "ti", "compute", "ti.t", "-H", "hti"],
  "done_if": ["ti.t/result.json"]
}
```

## Commands

```bash
dpti workflow run workflow.json
dpti workflow status workflow.json
dpti workflow run workflow.json --from-step hti.gen
dpti workflow run workflow.json --rerun-all
dpti workflow run workflow.json --dry-run
dpti workflow run workflow.json --jobs 3
```

The workflow state is stored in `workflow_state.json` by default.  If a run is
interrupted, rerunning `dpti workflow run workflow.json` continues from the saved
state and verifies the `done_if` outputs before skipping completed steps.
