import time
from dataclasses import dataclass
from datetime import timedelta
from typing import List

from geopandas import GeoDataFrame
import pandas as pd
import geopandas as gpd
from geopy import Point
from matplotlib import pyplot as plt
from movingpandas.time_range_utils import TemporalRange
from shapely import Polygon

from sdk.moveapps_spec import hook_impl
from movingpandas import TrajectoryCollection, TrajectoryStopDetector, Trajectory
import logging
from movingpandas import trajectory_utils

@dataclass
class AppConfig:
    # The minimum number of hours that is considered a stop of interest
    min_duration_hours: float

    # maximum number of meters an animal can move and still be considered "stopped"
    max_diameter_meters: int

    # only look at the final stop in a given trajectory if more than one exist
    final_stop_only: bool


class App(object):

    def __init__(self, moveapps_io):
        self.moveapps_io = moveapps_io

        self.all_stop_points = GeoDataFrame()
        self.final_stop_points = GeoDataFrame()
        self.segments_after_final_stop: List[Trajectory] = []

        self.app_config = self.map_config({})  # default configuration

    @staticmethod
    def map_config(config: dict):
        return AppConfig(
            min_duration_hours=config['min_duration_hours'] if 'min_duration_hours' in config else 72,
            max_diameter_meters=config['max_diameter_meters'] if 'max_diameter_meters' in config else 100,
            final_stop_only=config["final_stop_only"] if "final_stop_only" in config else True
        )

    @staticmethod
    def get_stop_to_end_trajectory(traj: TrajectoryCollection, stop_end_time) -> Trajectory:
        """ Gets the trajectory segment between when the last stop occurred and when the last observation was.
        :param traj: the trajectory collection to be segmented
        :param stop_end_time: the time that the last stop ended
        :return: the trajectory segment between the stop end time and the final observation
        """
        final_observation_time = traj.df.timestamps.max()
        time_range = [TemporalRange(stop_end_time, final_observation_time)]
        return trajectory_utils.convert_time_ranges_to_segments(traj, time_range)[0]

    def get_distance_between_points(self, point1: Point, point2: Point):
        """ Calculates the distance between two points
        :param point1:
        :param point2:
        :return:
        """
        points_df = gpd.GeoDataFrame({'geometry': [point2, point1]}, crs='EPSG:5234')
        points_df = points_df.to_crs('EPSG:5234')
        points_df2 = points_df.shift()  # We shift the dataframe by 1 to align pnt1 with pnt2
        distance = points_df.distance(points_df2)
        return distance

    def get_last_stop_point(self, traj_collection: TrajectoryCollection) -> GeoDataFrame | None:
        traj_collection.df.sort_values(by=['timestamps'], ascending=False)

        detector = TrajectoryStopDetector(traj_collection)
        stop_points = detector.get_stop_points(min_duration=timedelta(hours=self.app_config.min_duration_hours),
                                               max_diameter=self.app_config.max_diameter_meters)

        if not stop_points.empty:
            # sort by end time
            stop_points.sort_values(by=['end_time'], ascending=False)

            self.all_stop_points = pd.concat([self.all_stop_points, stop_points])

            # get last stop
            final_stop = stop_points.iloc[[-1]].copy()

            final_stop_position = final_stop.geometry[0]
            final_observation_position = traj_collection.df.iloc[[-1]].copy().geometry[0]

            # distance = self.__get_distance_between_points(final_stop_position, final_observation_position)

            # check if there is further movement after the final stop point
            final_observation_time = traj_collection.df.timestamps.max()
            final_stop['final_observation_time'] = final_observation_time
            # final_stop['distance_moved_from_final_stop'] = distance[1]

            time_tracked_since_stop = final_observation_time - final_stop.end_time[0]
            final_stop['time_tracked_since_final_stop'] = time_tracked_since_stop
            final_stop['mean_rate_all_tracks'] = traj_collection.df["speed"].mean()

            final_segment = self.get_stop_to_end_trajectory(traj_collection, final_stop.end_time[0])

            # add to list of final segments
            self.segments_after_final_stop.append(final_segment)

            final_segment.add_distance(overwrite=True, name="distance (m)", units="m")
            final_stop['distance_traveled_since_final_stop'] = final_segment.df['distance (m)'].sum()
            # final_stop['absolute distance from final stop'] =
            final_segment.add_speed(overwrite=True, units=("m", "s"))
            final_stop['average_rate_since_final_stop'] = final_segment.df.speed.mean()
            if final_segment.df['distance (m)'].sum() < 200:
                print("small final seg", final_segment)

            # add to list of stop points
            self.final_stop_points = pd.concat([self.final_stop_points, final_stop])
        pass

    def __add_duration_label(self, ax) -> None:
        """ Adds a label for the stop duration time (hours).
        :param ax: the plot axis
        """
        for x, y, label in zip(self.final_stop_points.geometry.x, self.final_stop_points.geometry.y, self.final_stop_points.duration_s / 3600):
            ax.annotate("{:.2f} hours".format(label), xy=(x, y), xytext=(3, 15), textcoords="offset points")

    def __add_traj_id_label(self, ax) -> None:
        """ Adds a label for trajectory ID to the plot.
        :param ax: the plot axis
        """
        for x, y, label in zip(self.final_stop_points.geometry.x, self.final_stop_points.geometry.y, self.final_stop_points.traj_id):
            ax.annotate(label, xy=(x, y), xytext=(3, 3), textcoords="offset points")

    @staticmethod
    def scale_marker_size(column) -> float:
        """ Scales a column to be used for normalized marker size.
        :param column:
        :return:
        """
        if column.max() - column.min() > 0:
            normalized_df = column - column.min() + 1 / (column.max() - column.min())
            return normalized_df * 100
        return column

    def __get_clip_polygon(self) -> Polygon:
        """ Returns a polygon representing the area encompassed by the stop points.
        :return: a polygon representing the area encompassed by the stop points
        """
        max_lat = self.final_stop_points.geometry.y.max()
        min_lat = self.final_stop_points.geometry.y.min()

        max_lon = self.final_stop_points.geometry.x.max()
        min_lon = self.final_stop_points.geometry.x.min()

        return Polygon(
            [(min_lon, min_lat), (min_lon, max_lat), (max_lon, max_lat), (max_lon, min_lat), (min_lon, min_lat)])

    @hook_impl
    def execute(self, data: TrajectoryCollection, config: dict) -> TrajectoryCollection:
        """ Your app code goes here. """
        logging.info(f'Running Stop Detection app on {len(data.trajectories)} trajectories with {config}')
        self.app_config = self.map_config(config)  # override with user input

        for tr in data.trajectories:
            tr.crs_units = tr.df.crs.axis_info[0].unit_name
            tr.add_speed(overwrite=True, units=("m", "s"))
            self.get_last_stop_point(tr)

        self.generate_plot()

        print(self.final_stop_points)
        return self.final_stop_points

    def generate_plot(self):
        marker_size = self.scale_marker_size(self.final_stop_points['duration_s'])
        # initialize an axis
        ax = TrajectoryCollection(self.segments_after_final_stop).plot(figsize=(8, 8))
        self.__add_traj_id_label(ax)
        self.__add_duration_label(ax)
        self.final_stop_points.plot(ax=ax, color='deeppink', markersize=100, legend=True, alpha=1, zorder=20)
