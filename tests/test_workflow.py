import json
import os
import shutil
import sys
import unittest
from pathlib import Path

from context import dpti
import dpti.workflow


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.work_dir = Path("tmp_workflow")
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)
        self.work_dir.mkdir()

    def tearDown(self):
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)

    def _write_workflow(self):
        workflow = {
            "work_base": ".",
            "steps": [
                {
                    "name": "make-a",
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('a.txt').write_text('a')",
                    ],
                    "done_if": "a.txt",
                },
                {
                    "name": "make-b",
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('b.txt').write_text('b')",
                    ],
                    "done_if": ["b.txt"],
                },
            ],
        }
        workflow_file = self.work_dir / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))
        return workflow_file

    def test_run_and_skip_completed_steps(self):
        workflow_file = self._write_workflow()
        dpti.workflow.run_workflow(str(workflow_file))

        state = json.loads((self.work_dir / "workflow_state.json").read_text())
        self.assertEqual(state["steps"]["make-a"]["status"], "completed")
        self.assertEqual(state["steps"]["make-b"]["status"], "completed")
        self.assertTrue((self.work_dir / "a.txt").is_file())
        self.assertTrue((self.work_dir / "b.txt").is_file())

        os.remove(self.work_dir / "b.txt")
        dpti.workflow.run_workflow(str(workflow_file))

        state = json.loads((self.work_dir / "workflow_state.json").read_text())
        self.assertEqual(state["steps"]["make-a"]["status"], "completed")
        self.assertEqual(state["steps"]["make-b"]["status"], "completed")
        self.assertTrue((self.work_dir / "b.txt").is_file())

    def test_done_if_glob_requires_all_existing_task_outputs(self):
        (self.work_dir / "task.000000").mkdir()
        (self.work_dir / "task.000001").mkdir()
        (self.work_dir / "task.000000" / "log.lammps").write_text("done")
        workflow = {
            "work_base": ".",
            "steps": [
                {
                    "name": "finish-tasks",
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; "
                        "Path('task.000001/log.lammps').write_text('done')",
                    ],
                    "done_if": "task.*/log.lammps",
                }
            ],
        }
        workflow_file = self.work_dir / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        state = {
            "steps": {
                "finish-tasks": {
                    "status": "completed",
                }
            }
        }
        (self.work_dir / "workflow_state.json").write_text(json.dumps(state))
        dpti.workflow.run_workflow(str(workflow_file))

        self.assertTrue((self.work_dir / "task.000000" / "log.lammps").is_file())
        self.assertTrue((self.work_dir / "task.000001" / "log.lammps").is_file())

    def test_explicit_needs_can_break_implicit_serial_order(self):
        workflow = {
            "work_base": ".",
            "steps": [
                {
                    "name": "make-a",
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('a.txt').write_text('a')",
                    ],
                    "done_if": "a.txt",
                },
                {
                    "name": "make-b",
                    "needs": [],
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('b.txt').write_text('b')",
                    ],
                    "done_if": "b.txt",
                },
                {
                    "name": "make-c",
                    "needs": ["make-a", "make-b"],
                    "command": [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('c.txt').write_text('c')",
                    ],
                    "done_if": "c.txt",
                },
            ],
        }
        workflow_file = self.work_dir / "workflow.json"
        workflow_file.write_text(json.dumps(workflow))

        dpti.workflow.run_workflow(str(workflow_file), jobs=2)

        state = json.loads((self.work_dir / "workflow_state.json").read_text())
        self.assertEqual(state["steps"]["make-a"]["status"], "completed")
        self.assertEqual(state["steps"]["make-b"]["status"], "completed")
        self.assertEqual(state["steps"]["make-c"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
