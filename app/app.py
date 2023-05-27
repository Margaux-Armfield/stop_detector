import time
import webbrowser
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

import folium
from geopandas import GeoDataFrame
import pandas as pd
from movingpandas.geometry_utils import mrr_diagonal
from movingpandas.time_range_utils import TemporalRange, TemporalRangeWithTrajId
from movingpandas.trajectory_utils import convert_time_ranges_to_segments
from pandas import Series, Timestamp
from shapely import Polygon, MultiPoint, Point

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
    def get_stop_to_end_trajectory(traj: Trajectory, stop_end_time: Timestamp) -> Optional[Trajectory]:
        """ Gets the trajectory segment between when the last stop occurred and when the last observation was.
        :param traj: the trajectory to be segmented
        :param stop_end_time: the time that the last stop ended
        :return: the trajectory segment between the stop end time and the final observation
        """
        final_observation_time = traj.df.timestamps.max()
        time_range = [TemporalRange(stop_end_time, final_observation_time)]
        if len(trajectory_utils.convert_time_ranges_to_segments(traj, time_range)) >= 1:
            return trajectory_utils.convert_time_ranges_to_segments(traj, time_range)[0]
        return None

    def get_most_recent_stop_only(self, traj):
        """ Extracts to most recent long stop from the trajectory.
        :param traj: the trajectory to check
        :return: the most recent stop point
        """
        stop_time_ranges = self.get_stop_time_range(traj)
        stops = TrajectoryCollection(
            convert_time_ranges_to_segments(traj, stop_time_ranges)
        )

        stop_pts = GeoDataFrame(columns=["geometry"]).set_geometry("geometry")
        stop_pts["stop_id"] = [track.id for track in stops.trajectories]
        stop_pts = stop_pts.set_index("stop_id")

        for stop in stops:
            stop_pts.at[stop.id, "start_time"] = stop.get_start_time()
            stop_pts.at[stop.id, "end_time"] = stop.get_end_time()
            pt = Point(stop.df.geometry.x.median(), stop.df.geometry.y.median())
            stop_pts.at[stop.id, "geometry"] = pt
            stop_pts.at[stop.id, "traj_id"] = stop.parent.id

        if len(stops) > 0:
            stop_pts["duration_s"] = (
                    stop_pts["end_time"] - stop_pts["start_time"]
            ).dt.total_seconds()
            stop_pts["traj_id"] = stop_pts["traj_id"].astype(type(stop.parent.id))

        return stop_pts

    def get_stop_time_range(self, traj):
        segment_geoms = []
        segment_times = []
        geom = MultiPoint()
        is_stopped = False
        previously_stopped = False
        min_duration = timedelta(hours=self.app_config.min_duration_hours)

        for index, data in traj.df[traj.get_geom_column_name()].items():
            segment_geoms.append(data)
            geom = geom.union(data)
            segment_times.append(index)

            if not is_stopped:  # remove points to the specified min_duration
                while (len(segment_geoms) > 2
                        and segment_times[-1] - segment_times[0] >= min_duration
                ):
                    segment_geoms.pop(0)
                    segment_times.pop(0)
                # after removing extra points, re-generate geometry
                geom = MultiPoint(segment_geoms)

            if (len(segment_geoms) > 1 and mrr_diagonal(geom, traj.is_latlon) < self.app_config.max_diameter_meters ):
                is_stopped = True
            else:
                is_stopped = False

            if len(segment_geoms) > 1:
                segment_end = segment_times[-2]
                segment_begin = segment_times[0]
                if not is_stopped and previously_stopped:
                    if (segment_end - segment_begin >= min_duration):  # detected end of a stop
                        return [TemporalRangeWithTrajId(segment_begin, segment_end, traj.id)]

            previously_stopped = is_stopped

        if is_stopped and segment_times[-1] - segment_times[0] >= min_duration:
            return [TemporalRangeWithTrajId(segment_times[0], segment_times[-1], traj.id)]

        return []

    def get_last_stop_point(self, trajectory: Trajectory) -> None:
        """ Gets the final stop point (based on configuration params) in the trajectory.
        :param trajectory: the trajectory to check for stop detections
        """
        trajectory.df.sort_values(by=['timestamps'], ascending=False)

        detector = TrajectoryStopDetector(trajectory)
        stop_points = detector.get_stop_points(min_duration=timedelta(hours=self.app_config.min_duration_hours),
                                               max_diameter=self.app_config.max_diameter_meters)

        if not stop_points.empty:
            # sort by end time
            stop_points.sort_values(by=['end_time'], ascending=False)

            self.all_stop_points = pd.concat([self.all_stop_points, stop_points])

            # get last stop
            final_stop: GeoDataFrame = stop_points.iloc[[-1]].copy()

            # check if there is further movement after the final stop point
            final_observation_time = trajectory.df.timestamps.max()
            final_stop['final_observation_time'] = final_observation_time
            # final_stop['distance_moved_from_final_stop'] = distance[1]

            # time_tracked_since_final_stop
            time_tracked_since_stop = final_observation_time - final_stop.end_time[0]
            final_stop['time_tracked_since_final_stop'] = time_tracked_since_stop

            # mean_rate_all_tracks
            trajectory.crs_units = trajectory.df.crs.axis_info[0].unit_name
            trajectory.add_speed(overwrite=True, units=("m", "s"))
            final_stop['mean_rate_all_tracks'] = trajectory.df["speed"].mean()

            final_segment: Optional[Trajectory] = self.get_stop_to_end_trajectory(trajectory, final_stop.end_time[0])

            # movement after final stop
            if final_segment is not None:
                final_segment.add_distance(overwrite=True, name="distance (m)", units="m")
                final_stop['distance_traveled_since_final_stop'] = final_segment.df['distance (m)'].sum()
                final_segment.add_speed(overwrite=True, units=("m", "s"))
                final_stop['average_rate_since_final_stop'] = final_segment.df.speed.mean()
                # add to list of final segments
                self.segments_after_final_stop.append(final_segment)
            else:
                # no final segment after stop
                final_stop['distance_traveled_since_final_stop'] = 0
                final_stop['average_rate_since_final_stop'] = 0

            # add to list of stop points
            self.final_stop_points = pd.concat([self.final_stop_points, final_stop])

    @staticmethod
    def scale_marker_size(column: Series) -> float:
        """ Scales a column to be used for normalized marker size.
        :param column:
        :return:
        """
        min_marker_size = 50
        med_marker_size = 100
        max_marker_size = 400
        scaler = med_marker_size / column.mean()

        new_column = column * scaler
        new_column.clip(lower=min_marker_size, upper=max_marker_size)
        return new_column

    @hook_impl
    def execute(self, data: TrajectoryCollection, config: dict) -> TrajectoryCollection:
        """
        Executes the application.
        :param data: a collection of trajectories to analyze for stops
        :param config: the app configuration settings
        :return: a collection of stop trajectories
        """
        logging.info(f'Running Stop Detection app on {len(data.trajectories)} trajectories with {config}')
        self.app_config = self.map_config(config)  # override with user input

        # iterate through trajectories and look for stops
        for tr in data.trajectories:
            self.get_last_stop_point(tr)

        self.generate_plot()

        print(self.final_stop_points)
        # TODO: output stop points to csv file
        return self.final_stop_points

    def generate_plot(self):
        """ Creates a plot to display stops and final segments.
        :return: None
        """
        df = self.final_stop_points.copy() if self.app_config.final_stop_only else self.all_stop_points
        df['start_time'] = df['start_time'].astype(str)
        df['end_time'] = df['end_time'].astype(str)
        df['final_observation_time'] = df['final_observation_time'].astype(str)
        df["duration_s"] = df['duration_s'].astype(str)
        df["time_tracked_since_final_stop"] = df['time_tracked_since_final_stop'].astype(str)

        max_lat = self.final_stop_points.geometry.y.max()
        min_lat = self.final_stop_points.geometry.y.min()
        max_lon = self.final_stop_points.geometry.x.max()
        min_lon = self.final_stop_points.geometry.x.min()

        map = folium.Map(location=[df.dissolve().centroid.y.iloc[0], df.dissolve().centroid.x.iloc[0]], zoom_start=6)

        show_final_trajectories = True
        if show_final_trajectories and len(self.segments_after_final_stop) > 0:
            # add final segments to map
            segments_as_dataframe = TrajectoryCollection(self.segments_after_final_stop).to_traj_gdf().geometry

            for i in range(len(segments_as_dataframe)):
                locations = []
                for j in segments_as_dataframe[i].coords:
                    locations.append((j[1], j[0]))

                folium.PolyLine(locations, color="red", weight=2.5, opacity=1).add_to(map)

        map_output_hmtl = df.explore(
            column="traj_id",
            tooltip="traj_id",
            m=map.fit_bounds(bounds=[(min_lat, min_lon), (max_lat, max_lon)]),
            popup=True,  # show all values in popup (on click)
            cmap="Set1",  # use "Set1" matplotlib colormap
            style_kwds=dict(color="black"),  # use black outline
            marker_kwds=dict(radius=5, fill=True, opacity=1),  # make marker radius 10px with fill
        )

        map_output_hmtl.save('/Users/margauxarmfield/Downloads/test.html')

        # TODO point size based on time
        # marker_size = self.scale_marker_size(self.final_stop_points['duration_s'])
