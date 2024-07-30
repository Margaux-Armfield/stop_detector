import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional

import folium
import pandas as pd
from geopandas import GeoDataFrame
from movingpandas import TrajectoryCollection, TrajectoryStopDetector, Trajectory
from movingpandas import trajectory_utils
from movingpandas.time_range_utils import TemporalRange

from pandas import Timestamp

from sdk.moveapps_spec import hook_impl


@dataclass
class AppConfig:
    # The minimum number of hours that is considered a stop of interest
    min_duration_hours: float

    # The maximum number of meters an animal can move and still be considered "stopped"
    max_diameter_meters: int

    # Whether the app should only look at the final stop in a given trajectory if more than one exist
    final_stops_only: bool

    # Whether trajectories after final stops should be displayed on the map
    display_trajectories_after_stops: bool

    # The output data returned from app at completion ("input_data" or "trajectories")
    return_data: str

    def __post_init__(self):
        """ Ensures AppConfig was initialized with valid values.
        """
        assert self.max_diameter_meters is not None and self.max_diameter_meters > 0
        assert self.min_duration_hours is not None and self.min_duration_hours > 0
        assert self.final_stops_only is not None and self.final_stops_only in [True, False]
        assert self.display_trajectories_after_stops is not None and \
               self.display_trajectories_after_stops in [True, False]
        assert self.return_data in ["input_data", "trajectories"]


class App(object):

    def __init__(self, moveapps_io):
        """ Initialized this application.
        :param moveapps_io: utility for input and output
        """
        self.moveapps_io = moveapps_io

        self.all_stop_points = GeoDataFrame()
        self.final_stop_points = GeoDataFrame()

        self.trajectories_after_all_stops: List[Trajectory] = []
        self.trajectories_after_final_stop: List[Trajectory] = []

        self.app_config = self.map_config({})  # default configuration

    @staticmethod
    def map_config(config: dict) -> AppConfig:
        """ Maps a configuration dictionary to an App Config object.
        :param config: the config dictionary
        :return: an AppConfig
        """
        return AppConfig(
            min_duration_hours=config.get('min_duration_hours', 120),
            max_diameter_meters=config.get('max_diameter_meters', 100),
            final_stops_only=config.get("final_stops_only", True),
            display_trajectories_after_stops=config.get("display_trajectories_after_stops", True),
            return_data=config.get("return_data", "input_data")
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

    def add_stop_data(self, stop: GeoDataFrame, trajectory) -> Optional[Trajectory]:
        """ Add data for stop and segment after stop.
        :param stop: the stop point to analyze
        :param trajectory: the trajectory that the stop point is part of
        """
        # check if there is further movement after the final stop point
        final_observation_time = Timestamp(trajectory.df.timestamps.max())
        stop['final_observation_time'] = final_observation_time

        time_tracked_since_stop = final_observation_time - stop.start_time.iloc[0]
        stop['time_tracked_since_stop_began'] = time_tracked_since_stop

        # mean_rate_all_tracks
        trajectory.crs_units = trajectory.df.crs.axis_info[0].unit_name
        trajectory.add_speed(overwrite=True, units=("m", "s"))
        stop['mean_rate_all_tracks'] = trajectory.df["speed"].mean()

        segment: Optional[Trajectory] = self.get_stop_to_end_trajectory(trajectory, stop.start_time.iloc[0])

        # movement after final stop
        if segment is not None:
            segment.add_distance(overwrite=True, name="distance (m)", units="m")
            stop['distance_traveled_since_stop_began'] = segment.df['distance (m)'].sum()
            segment.add_speed(overwrite=True, units=("m", "s"))
            stop['average_rate_since_stop_began'] = segment.df.speed.mean()
            self.trajectories_after_all_stops.append(segment)
        else:
            # no final segment after stop
            stop['distance_traveled_since_stop_began'] = 0
            stop['average_rate_since_stop_began'] = 0

        self.all_stop_points = pd.concat([self.all_stop_points, stop])
        return segment

    def get_stops(self, trajectory: Trajectory) -> None:
        """ Gets the stop point(s) based on configuration params and the trajectory.
        :param trajectory: the trajectory to check for stop detections
        """
        trajectory.df.sort_values(by=['timestamps'], ascending=False)

        detector = TrajectoryStopDetector(trajectory)
        stop_points = detector.get_stop_points(min_duration=timedelta(hours=self.app_config.min_duration_hours),
                                               max_diameter=self.app_config.max_diameter_meters)

        if not stop_points.empty:
            # sort by end time
            stop_points.sort_values(by=['end_time'], ascending=True)

            if not self.app_config.final_stops_only:
                # get all stop points besides the final one
                for i in range(len(stop_points) - 1):
                    stop = stop_points.iloc[[i]].copy()
                    self.add_stop_data(stop, trajectory)

            # get final stop and final segment if it exists
            final_stop: GeoDataFrame = stop_points.iloc[[-1]].copy()
            final_segment = self.add_stop_data(final_stop, trajectory)

            # add to list of final stop points
            self.final_stop_points = pd.concat([self.final_stop_points, final_stop])

            if final_segment is not None:
                self.trajectories_after_final_stop.append(final_segment)

    @hook_impl
    def execute(self, data: TrajectoryCollection, config: dict) -> TrajectoryCollection:
        """ Executes the application.
        :param data: a collection of trajectories to analyze for stops
        :param config: the app configuration settings
        :return: a collection of stop points as trajectories
        """
        logging.info(f'Running Stop Detection app on {len(data.trajectories)} trajectories with {config}')
        self.app_config = self.map_config(config)  # override with user input

        # iterate through trajectories and look for stops
        for tr in data.trajectories:
            self.get_stops(tr)

        self.generate_plot()

        # write csv output files
        self.final_stop_points.to_csv(self.moveapps_io.create_artifacts_file('final_stops.csv'))

        if not self.app_config.final_stops_only:
            self.all_stop_points.to_csv(self.moveapps_io.create_artifacts_file('all_stops.csv'))

        if self.app_config.return_data == "trajectories":
            if self.app_config.final_stops_only:
                return TrajectoryCollection(self.trajectories_after_final_stop, traj_id_col="traj_id")
            else:
                return TrajectoryCollection(self.trajectories_after_all_stops, traj_id_col="traj_id")
        return data

    def generate_plot(self) -> None:
        """ Creates a map to display stops and final trajectories. """
        stops = self.final_stop_points.copy() if self.app_config.final_stops_only else self.all_stop_points.copy()
        if len(stops) > 0:
            # rename fields to be more human friendly
            stops['Stop Start Time'] = stops['start_time'].astype(str)
            stops['Stop End Time'] = stops['end_time'].astype(str)
            stops['Final Observation Time'] = stops['final_observation_time'].astype(str)
            stops["Stop Duration in Hours"] = (stops['duration_s'] / 3600).astype(str)
            stops["Time Tracked Since Stop Began"] = stops['time_tracked_since_stop_began'].astype(str)
            stops.index = stops.index.rename("Stop ID")
            # drop duplicates
            stops = stops.drop(
                columns=['duration_s',
                         'start_time',
                         'end_time',
                         'final_observation_time',
                         'time_tracked_since_stop_began'])
            stops = stops.rename(
                columns={'distance_traveled_since_stop_began': 'Distance Traveled Since Stop Began (meters)',
                         'traj_id': 'Traj ID',
                         'average_rate_since_stop_began': "Average Rate Since Stop Began (meters / second)",
                         'mean_rate_all_tracks': 'Mean Rate of All Tracks (meters / second)'})

            folium_map = folium.Map(location=[stops.dissolve().centroid.y.iloc[0],
                                              stops.dissolve().centroid.x.iloc[0]],
                                    zoom_start=6)

            segments = self.trajectories_after_final_stop if self.app_config.final_stops_only \
                else self.trajectories_after_all_stops

            if self.app_config.display_trajectories_after_stops and len(segments) > 0:
                # add final segments to map
                segments_as_dataframe = TrajectoryCollection(segments).to_traj_gdf()

                # style function
                style_function = lambda x: {
                    # specifying properties from GeoJSON
                    'color': x['properties']['stroke'],
                    'opacity': 0.50,
                    'weight': x['properties']['stroke-width']
                }

                # highlight function (change displayed on hover)
                highlight_function = lambda x: {
                    'color': 'blue',
                    'opacity': 1.0,
                    # specifying properties from GeoJSON
                    'weight': x['properties']['stroke-width']
                }

                for i in range(len(segments_as_dataframe)):
                    locations = []
                    for j in segments_as_dataframe.geometry[i].coords:
                        locations.append([j[0], j[1]])

                    trajectory_geojson = {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "properties": {
                                    "stroke": "#aa0000",
                                    "stroke-width": 4,
                                    "stroke-opacity": 1
                                },
                                "geometry": {
                                    "type": "LineString",
                                    "coordinates": locations
                                }
                            },
                        ]
                    }
                    # add trajectory to map using folium geojson and support highlighting on hover
                    traj_info = folium.features.GeoJson(
                        trajectory_geojson,
                        name='trajectory',
                        control=True,
                        style_function=style_function,
                        highlight_function=highlight_function,
                        tooltip=segments_as_dataframe["traj_id"][i]
                    )
                    folium_map.add_child(traj_info)

            map_output_hmtl = stops.explore(
                column="Traj ID",
                tooltip="Traj ID",
                m=folium_map,
                legend=True,
                popup=True,  # show all values in popup (on click)
                cmap="tab20",  # use "tab20" matplotlib colormap
                style_kwds=dict(color="black"),  # use black outline
                popup_kwds=dict(min_width=500,max_width=800),
                marker_kwds=dict(radius=7, fill=True, opacity=1),  # make marker radius 7px with fill
            )

            map_output_hmtl.save(self.moveapps_io.create_artifacts_file('map.html'))

        else:
            logging.warning("No stops detected in data set. Could not create map.")
            with open(self.moveapps_io.create_artifacts_file('empty_map.html'), 'w') as f:
                f.write('''<html>
                            <body>         
                            <p>No stops detected in dataset with configuration: {}</p>
                            <p>
                            <p>Consider decreasing duration or increasing diameter.</p> 
                            </body>
                            </html>'''.format(self.app_config))
                f.close()
