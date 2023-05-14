import time
from dataclasses import dataclass
from datetime import timedelta

from geopandas import GeoDataFrame
import pandas as pd
import geopandas as gpd
from movingpandas.time_range_utils import TemporalRange

from sdk.moveapps_spec import hook_impl
from movingpandas import TrajectoryCollection, TrajectoryStopDetector, Trajectory
import logging
from movingpandas import trajectory_utils

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
        self.app_config = self.map_config({})  # default configuration

    @staticmethod
    def map_config(config: dict):
        return AppConfig(
            min_duration_hours=config['min_duration_hours'] if 'min_duration_hours' in config else 72,
            max_diameter_meters=config['max_diameter_meters'] if 'max_diameter_meters' in config else 100
        )

    @staticmethod
    def get_stop_to_end_trajectory(traj, stop_end_time) -> Trajectory:
        """
        Gets the trajectory segment between when the last stop occurred and when the last observation was.
        :param traj: the trajectory to be segmented
        :param stop_end_time: the time that the last stop ended
        :return: the trajectory segment between the stop end time and the final observation
        """
        final_observation_time = traj.df.timestamps.max()
        time_range = [TemporalRange(stop_end_time, final_observation_time)]
        return trajectory_utils.convert_time_ranges_to_segments(traj, time_range)[0]

    def get_last_stop_point(self, tr: TrajectoryCollection) -> GeoDataFrame | None:
        tr.df.sort_values(by=['timestamps'], ascending=False)

        detector = TrajectoryStopDetector(tr)
        stop_points = detector.get_stop_points(min_duration=timedelta(hours=self.app_config.min_duration_hours),
                                               max_diameter=self.app_config.max_diameter_meters)

        if not stop_points.empty:
            # sort by end time
            stop_points.sort_values(by=['end_time'], ascending=False)
            # get last stop
            final_stop = stop_points.iloc[[-1]].copy()

            final_stop_position = final_stop.geometry[0]
            final_observation = tr.df.iloc[[-1]].copy().geometry[0]
            points_df = gpd.GeoDataFrame({'geometry': [final_stop_position, final_observation]}, crs='EPSG:4326')
            points_df = points_df.to_crs('EPSG:5234')
            points_df2 = points_df.shift()  # We shift the dataframe by 1 to align pnt1 with pnt2
            distance = points_df.distance(points_df2)
            print("distance from final obs: ", distance[1])

            # check if there is further movement after the final stop point
            final_observation_time = tr.df.timestamps.max()
            assert final_observation_time == tr.df.iloc[[-1]].copy().timestamps[0], "time difference unexpected"

            final_stop['final_observation_time'] = final_observation_time
            # final_stop['distance_moved_from_final_stop'] = distance[1]

            time_tracked_since_stop = final_stop.final_observation_time[0] - final_stop.end_time[0]
            final_stop['time_tracked_since_final_stop'] = time_tracked_since_stop
            final_stop['mean_rate_all_tracks'] = tr.df["speed"].mean()

            final_segment = self.get_stop_to_end_trajectory(tr, final_stop.end_time[0])
            final_segment.add_distance(overwrite=True, name="distance (m)", units="m")
            final_stop['distance_traveled_since_final_stop'] = final_segment.df['distance (m)'].sum()
            final_segment.add_speed(overwrite=True, units=("m", "s"))
            final_stop['averge_rate_since_final_stop'] = final_segment.df.speed.mean()

            print(final_segment)

            # add to list of stop points
            if self.stop_points is None:
                self.stop_points = final_stop
            else:
                self.stop_points = pd.concat([self.stop_points, final_stop])
        pass

    def __add_duration_label(self, ax):
        for x, y, label in zip(self.stop_points.geometry.x, self.stop_points.geometry.y, self.stop_points.duration_s / 3600):
            ax.annotate("{:.2f} hours".format(label), xy=(x, y), xytext=(3, 15), textcoords="offset points")

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
        self.app_config = self.map_config(config)  # override with user input

        for tr in data.trajectories:
            tr.crs_units = tr.df.crs.axis_info[0].unit_name
            tr.add_speed(overwrite=True, units=("m", "s"))
            self.get_last_stop_point(tr)

        marker_size = self.scale_marker_size(self.stop_points['duration_s'])
        ax = self.stop_points.plot(figsize=(9, 5), linewidth=3)
        self.__add_traj_id_label(ax)
        self.__add_duration_label(ax)
        self.stop_points.plot(ax=ax, color='deeppink', markersize=marker_size, legend=True)

        print(self.stop_points)
        return self.stop_points
