import unittest
import os
from tests.config.definitions import ROOT_DIR
from app.app import App
from sdk.moveapps_io import MoveAppsIo
import pandas as pd
import movingpandas as mpd


class MyTestCase(unittest.TestCase):

    def setUp(self) -> None:
        os.environ['APP_ARTIFACTS_DIR'] = os.path.join(ROOT_DIR, 'tests/resources/output')
        self.sut = App(moveapps_io=MoveAppsIo())

    def test_app_returns_input(self):
        # prepare
        expected: mpd.TrajectoryCollection = pd.read_pickle(os.path.join(ROOT_DIR, 'tests/resources/app/input2.pickle'))
        config: dict = {
            "min_duration_hours": 30,
            "max_diameter_meters": 100,
            "final_stop_only": False,
            "display_trajectories_after_stops": True,
            "return_data": "input_data"
        }

        # execute
        actual = self.sut.execute(data=expected, config=config)

        # verif
        self.assertEqual(expected, actual)

    def test_input2(self):
        # prepare
        input: mpd.TrajectoryCollection = pd.read_pickle(os.path.join(ROOT_DIR, 'tests/resources/app/input2.pickle'))
        expected: mpd.TrajectoryCollection = pd.read_pickle(os.path.join(ROOT_DIR,
                                                                         'tests/resources/output/output.pickle'))

        config: dict = {
            "min_duration_hours": 30,
            "max_diameter_meters": 100,
            "final_stop_only": False,
            "display_trajectories_after_stops": True,
            "return_data": "trajectories"
        }

        # execute
        actual = self.sut.execute(data=input, config=config)

        # number of trajectories
        self.assertEqual(2, len(actual.trajectories))
        # number of stop points
        self.assertEqual(534, len(actual.to_point_gdf()))

        # verify
        self.assertEqual(expected.trajectories, actual.trajectories)