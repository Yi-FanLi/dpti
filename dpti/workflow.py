import argparse
import concurrent.futures
import glob
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_STATE_FILE = "workflow_state.json"


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path):
    with open(path) as fp:
        return json.load(fp)


def _dump_json(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fp:
        json.dump(data, fp, indent=2)
        fp.write("\n")
    os.replace(tmp, path)


def _workflow_root(workflow_file, workflow):
    if "work_base" in workflow:
        root = Path(workflow["work_base"])
        if not root.is_absolute():
            root = Path(workflow_file).resolve().parent / root
        return root.resolve()
    return Path(workflow_file).resolve().parent


def _state_path(workflow_file, workflow):
    state_file = workflow.get("state_file", DEFAULT_STATE_FILE)
    state_path = Path(state_file)
    if not state_path.is_absolute():
        state_path = _workflow_root(workflow_file, workflow) / state_path
    return state_path


def _load_state(path):
    if not os.path.isfile(path):
        return {"created_at": _now(), "steps": {}}
    return _load_json(path)


def _step_work_dir(root, step):
    work_dir = Path(step.get("work_dir", "."))
    if not work_dir.is_absolute():
        work_dir = root / work_dir
    return work_dir.resolve()


def _as_command(command):
    if isinstance(command, str):
        return shlex.split(command)
    if isinstance(command, list):
        return [str(item) for item in command]
    raise TypeError("workflow step command must be a string or a list")


def _normalize_command(command):
    command = _as_command(command)
    if command and command[0] == "dpti":
        return [sys.executable, "-m", "dpti.main"] + command[1:]
    return command


def _check_paths(paths, work_dir):
    missing = []
    for required in _expand_required_paths(paths, work_dir):
        if not required.exists():
            missing.append(str(required))
    return missing


def _expand_required_paths(paths, work_dir):
    required = []
    for path in paths:
        path = Path(path)
        if not path.is_absolute():
            path = work_dir / path
        path_str = str(path)
        if not glob.has_magic(path_str):
            required.append(path)
            continue

        parent = path.parent
        name = path.name
        parent_str = str(parent)
        if glob.has_magic(parent_str) and not glob.has_magic(name):
            parents = sorted(Path(item) for item in glob.glob(parent_str))
            if not parents:
                required.append(path)
            else:
                required.extend(parent / name for parent in parents)
            continue

        matches = sorted(Path(item) for item in glob.glob(path_str))
        required.extend(matches or [path])
    return required


def _step_done(step, step_state, work_dir):
    if step_state.get("status") != "completed":
        return False
    done_if = step.get("done_if", [])
    if isinstance(done_if, str):
        done_if = [done_if]
    return not _check_paths(done_if, work_dir)


def _selected_steps(steps, from_step=None):
    if from_step is None:
        return steps
    names = [step["name"] for step in steps]
    if from_step not in names:
        raise ValueError(f"unknown workflow step: {from_step}")
    return steps[names.index(from_step) :]


def _step_dependencies(steps):
    dependencies = {}
    previous = None
    names = {step["name"] for step in steps}
    for step in steps:
        name = step["name"]
        if "needs" in step:
            needs = step["needs"]
            if isinstance(needs, str):
                needs = [needs]
            needs = list(needs)
        elif previous is None:
            needs = []
        else:
            needs = [previous]
        unknown = sorted(set(needs) - names)
        if unknown:
            raise ValueError(
                f"workflow step '{name}' depends on unknown steps: {unknown}"
            )
        dependencies[name] = needs
        previous = name
    return dependencies


def _run_one_step(step, root, dry_run=False):
    name = step["name"]
    if "command" not in step:
        raise ValueError(f"workflow step '{name}' does not define a command")
    work_dir = _step_work_dir(root, step)
    command = _normalize_command(step["command"])
    print(f"[workflow] run step: {name}")
    print(f"[workflow] cwd: {work_dir}")
    print("[workflow] command:", " ".join(shlex.quote(item) for item in command))
    if dry_run:
        return {"returncode": 0}
    work_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(command, cwd=str(work_dir))
    return {"returncode": completed.returncode}


def run_workflow(
    workflow_file,
    *,
    dry_run=False,
    rerun_all=False,
    from_step=None,
    jobs=1,
):
    workflow = _load_json(workflow_file)
    root = _workflow_root(workflow_file, workflow)
    all_steps = workflow.get("steps", [])
    steps = _selected_steps(all_steps, from_step=from_step)
    if not isinstance(steps, list) or len(steps) == 0:
        raise ValueError("workflow json must contain a non-empty 'steps' list")
    jobs = max(1, int(jobs))
    root.mkdir(parents=True, exist_ok=True)

    state_file = _state_path(workflow_file, workflow)
    state = _load_state(state_file)
    state["workflow_file"] = str(Path(workflow_file).resolve())
    state["work_base"] = str(root)
    state["updated_at"] = _now()

    dependencies = _step_dependencies(all_steps)
    selected_names = {step["name"] for step in steps}
    pending = {step["name"]: step for step in steps}
    running = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        while pending or running:
            submitted = False
            running_names = {step["name"] for step in running.values()}
            for name, step in list(pending.items()):
                needs = dependencies[name]
                if any(dep in pending or dep in running_names for dep in needs):
                    continue
                acceptable_status = ["completed"]
                if dry_run:
                    acceptable_status.append("dry_run")
                if any(
                    dep in selected_names
                    and state["steps"].get(dep, {}).get("status")
                    not in acceptable_status
                    for dep in needs
                ):
                    continue
                if any(
                    dep not in selected_names
                    and state["steps"].get(dep, {}).get("status") != "completed"
                    for dep in needs
                ):
                    continue

                work_dir = _step_work_dir(root, step)
                step_state = state["steps"].get(name, {})
                if not rerun_all and _step_done(step, step_state, work_dir):
                    print(f"[workflow] skip completed step: {name}")
                    pending.pop(name)
                    submitted = True
                    continue

                command = _normalize_command(step["command"])
                state["steps"][name] = {
                    "status": "running",
                    "command": command,
                    "work_dir": str(work_dir),
                    "started_at": _now(),
                }
                state["updated_at"] = _now()
                _dump_json(state_file, state)
                future = executor.submit(_run_one_step, step, root, dry_run)
                running[future] = step
                pending.pop(name)
                submitted = True

                if len(running) >= jobs:
                    break

            if running:
                done, _ = concurrent.futures.wait(
                    running,
                    timeout=0 if submitted and len(running) < jobs else None,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    step = running.pop(future)
                    name = step["name"]
                    result = future.result()
                    step_state = state["steps"][name]
                    step_state["finished_at"] = _now()
                    step_state["returncode"] = result["returncode"]
                    if dry_run:
                        step_state["status"] = "dry_run"
                        state["updated_at"] = _now()
                        _dump_json(state_file, state)
                        continue
                    if result["returncode"] != 0:
                        step_state["status"] = "failed"
                        state["updated_at"] = _now()
                        _dump_json(state_file, state)
                        raise RuntimeError(
                            f"workflow step '{name}' failed with return code "
                            f"{result['returncode']}"
                        )

                    done_if = step.get("done_if", [])
                    if isinstance(done_if, str):
                        done_if = [done_if]
                    missing = _check_paths(done_if, _step_work_dir(root, step))
                    if missing:
                        step_state["status"] = "failed"
                        step_state["missing_done_if"] = missing
                        state["updated_at"] = _now()
                        _dump_json(state_file, state)
                        raise RuntimeError(
                            f"workflow step '{name}' finished but required outputs "
                            f"are missing: {missing}"
                        )

                    step_state["status"] = "completed"
                    state["updated_at"] = _now()
                    _dump_json(state_file, state)
                continue

            if pending and not submitted:
                waiting = sorted(pending)
                raise RuntimeError(
                    f"workflow cannot make progress; waiting steps: {waiting}"
                )

    print(f"[workflow] state: {state_file}")
    return state


def print_status(workflow_file):
    workflow = _load_json(workflow_file)
    state_file = _state_path(workflow_file, workflow)
    state = _load_state(state_file)
    print(f"workflow: {Path(workflow_file).resolve()}")
    print(f"state: {state_file}")
    steps = workflow.get("steps", [])
    for step in steps:
        name = step["name"]
        status = state.get("steps", {}).get(name, {}).get("status", "pending")
        print(f"{name:30s} {status}")


def add_module_subparsers(main_subparsers):
    module_parser = main_subparsers.add_parser(
        "workflow", help="run and monitor high-level dpti workflows"
    )
    module_subparsers = module_parser.add_subparsers(
        help="commands for workflow orchestration", dest="command", required=True
    )

    parser_run = module_subparsers.add_parser("run", help="run a workflow json")
    parser_run.add_argument("WORKFLOW", type=str, help="workflow json file")
    parser_run.add_argument(
        "--dry-run", action="store_true", help="print and record steps without running"
    )
    parser_run.add_argument(
        "--rerun-all", action="store_true", help="rerun steps even if marked completed"
    )
    parser_run.add_argument(
        "--from-step", type=str, default=None, help="resume from the named step"
    )
    parser_run.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=1,
        help="maximum number of workflow steps to run at the same time",
    )
    parser_run.set_defaults(func=handle_run)

    parser_status = module_subparsers.add_parser("status", help="show workflow status")
    parser_status.add_argument("WORKFLOW", type=str, help="workflow json file")
    parser_status.set_defaults(func=handle_status)

    parser_resume = module_subparsers.add_parser(
        "resume", help="resume a workflow using the saved state file"
    )
    parser_resume.add_argument("WORKFLOW", type=str, help="workflow json file")
    parser_resume.add_argument(
        "--from-step", type=str, default=None, help="resume from the named step"
    )
    parser_resume.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=1,
        help="maximum number of workflow steps to run at the same time",
    )
    parser_resume.set_defaults(func=handle_resume)


def handle_run(args):
    run_workflow(
        args.WORKFLOW,
        dry_run=args.dry_run,
        rerun_all=args.rerun_all,
        from_step=args.from_step,
        jobs=args.jobs,
    )


def handle_resume(args):
    run_workflow(args.WORKFLOW, from_step=args.from_step, jobs=args.jobs)


def handle_status(args):
    print_status(args.WORKFLOW)
