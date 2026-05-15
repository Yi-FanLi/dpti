import json
import os
import shutil
import unittest
from unittest.mock import MagicMock, patch

from context import dpti

from dpti.lib.utils import get_file_md5


class TestGdiMakeTask(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.mkdir("tmp_gdi/")

    def setUp(self):
        self.maxDiff = None
        self.test_dir = "tmp_gdi"
        self.benchmark_dir = "benchmark_gdi"

    @patch("numpy.random.default_rng")
    def test_deepmd(self, patch_random):
        patch_random.return_value = MagicMock(integers=MagicMock(return_value=7858))
        test_name = "deepmd/0"
        benchmark_dir = os.path.join(self.benchmark_dir, test_name)
        test_dir = os.path.join(self.test_dir, test_name)

        json_file = os.path.join(benchmark_dir, "../", "pb.json")
        with open(json_file) as f:
            jdata = json.load(f)

        dpti.gdi._make_tasks_onephase(
            temp=300,
            pres=50000,
            task_path=test_dir,
            jdata=jdata,
            ens="npt",
            conf_file="conf.lmp",
            graph_file="graph.pb",
            if_meam=False,
            meam_model=None,
        )

        check_file_list = ["graph.pb", "conf.lmp", "in.lammps"]
        for file in check_file_list:
            f1 = os.path.join(benchmark_dir, file)
            f2 = os.path.join(test_dir, file)
            self.assertEqual(get_file_md5(f1), get_file_md5(f2), msg=(f1, f2))

    def test_setup_dpdt_phase_specific_models(self):
        parent_dir = os.path.join(self.test_dir, "phase_models")
        task_dir = os.path.join(parent_dir, "gdi_job")
        os.makedirs(parent_dir)
        shutil.copyfile("conf.lmp", os.path.join(parent_dir, "conf.0.lmp"))
        shutil.copyfile("alpha.lmp", os.path.join(parent_dir, "conf.1.lmp"))
        shutil.copyfile("graph.pb", os.path.join(parent_dir, "graph.0.pb"))
        shutil.copyfile("beta.lmp", os.path.join(parent_dir, "graph.1.pb"))
        jdata = {
            "phase_i": {
                "name": "PHASE_0",
                "equi_conf": "conf.0.lmp",
                "model": "graph.0.pb",
            },
            "phase_ii": {
                "name": "PHASE_1",
                "equi_conf": "conf.1.lmp",
                "model": "graph.1.pb",
            },
            "mass_map": [118.71],
            "nsteps": 5000,
            "timestep": 0.002,
            "tau_t": 0.1,
            "tau_p": 1.0,
            "thermo_freq": 10,
            "stat_skip": 100,
            "stat_bsize": 10,
        }

        dpti.gdi._setup_dpdt(task_dir, jdata)

        for file in ["conf.0.lmp", "conf.1.lmp", "graph.0.pb", "graph.1.pb"]:
            f1 = os.path.join(parent_dir, file)
            f2 = os.path.join(task_dir, file)
            self.assertEqual(get_file_md5(f1), get_file_md5(f2), msg=(f1, f2))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree("tmp_gdi/")


if __name__ == "__main__":
    unittest.main()
