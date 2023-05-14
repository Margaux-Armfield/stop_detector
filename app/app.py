import time
from dataclasses import dataclass
from datetime import timedelta

from geopandas import GeoDataFrame
import pandas as pd

from sdk.moveapps_spec import hook_impl
from movingpandas import TrajectoryCollection, TrajectoryStopDetector
import logging
import matplotlib as plt

@dataclass
class AppConfig:
    # The minimum number of hours that is considered a stop of interest
    min_duration_hours: float

    # maximum number of meters an animal can move and still be considered "stopped"
    max_diameter_meters: bool


class App(object):

    def __init__(self, moveapps_io):
        self.moveapps_io = moveapps_io
        self.stop_points = None

    @staticmethod
    def map_config(config: dict):
        return AppConfig(
            min_duration_hours=config['min_duration_hours'] if 'min_duration_hours' in config else 48,
            max_diameter_meters=config['max_diameter_meters'] if 'max_diameter_meters' in config else 25
        )

    def get_last_stop_point(self, tr: TrajectoryCollection) -> GeoDataFrame | None:
        detector = TrajectoryStopDetector(tr)
        stop_points = detector.get_stop_points(min_duration=timedelta(hours=40), max_diameter=100)

        if not stop_points.empty:
            # sort by end time
            stop_points.sort_values(by=['end_time'], ascending=False)
            # get last stop
            last_row = stop_points.iloc[[-1]]
            # check if there is further movement after the final stop point
            tr.df.iloc[[-1]]

            # add to list of stop points
            if self.stop_points is None:
                self.stop_points = last_row
            else:
                self.stop_points = pd.concat([self.stop_points, last_row])
        pass

    def __add_duration_label(self, ax):
        for x, y, label in zip(self.stop_points.geometry.x, self.stop_points.geometry.y, self.stop_points.duration_s / 3600):
            ax.annotate("{:.2f}".format(label), xy=(x, y), xytext=(3, 15), textcoords="offset points")

    def __add_traj_id_label(self, ax):
        """ Adds a label for trajectory ID to the plot.
        :param ax: the plot axis
        """
        for x, y, label in zip(self.stop_points.geometry.x, self.stop_points.geometry.y, self.stop_points.traj_id):
            ax.annotate(label, xy=(x, y), xytext=(3, 3), textcoords="offset points")

    def scale_marker_size(self, column):
        """ Scales a column to be used for normalized marker size.
        :param column:
        :return:
        """
        normalized_df = (column - column.min()) / (column.max() - column.min())
        return normalized_df * 100

    @hook_impl
    def execute(self, data: TrajectoryCollection, config: dict) -> TrajectoryCollection:
        """ Your app code goes here. """
        logging.info(f'Welcome to the {config}')

        for tr in data.trajectories:
            tr.plot(figsize=(9, 5), linewidth=3)
            self.get_last_stop_point(tr)

        ax = self.stop_points.plot(figsize=(9, 5), linewidth=3)
        self.__add_traj_id_label(ax)
        self.__add_duration_label(ax)

        marker_size = self.scale_marker_size(self.stop_points['duration_s'])
        self.stop_points.plot(ax=ax, color='deeppink', markersize=marker_size, legend=True)

        print(self.stop_points)
        return self.stop_points
