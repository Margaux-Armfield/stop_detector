# Armfield Detect Stationarity in GeoTags

MoveApps

Github repository: *github.com/yourAccount/Name-of-App* *(the link to the repository where the code of the app can be found must be provided)*

## Description

Identify and display stops in trajectory data from geotags. Set the time (in hours) and distance (meters) that is 
considered a "stop". Stops are displayed on a map, with the option to view any subsequent movement after the stop.

## Documentation

*Enter here a detailed description of your App. What is it intended to be used for. Which steps of analyses are performed and how. Please be explicit about any detail that is important for use and understanding of the App and its outcomes.*

### Input data

MovingPandas TrajectoryCollection in Movebank format

### Output data

MovingPandas TrajectoryCollection in Movebank format

### Artefacts

- `map.html` - an HTML file containing the Folium map, displaying stop points, with option to hover over points to show more data and zoom in / out.
- `all_stop_points.csv` - a csv file containing all the stop points detected matching the configuration parameters, with the following columns:
    - x
- `final_stop_points.csv` - a csv file containing the final stop points for individuals (i.e. most recent stop if there are more than one for a given individual), detected matching the configuration parameters, with the following columns: 


### Settings 

The following settings are required:

- `Minimum duration in hours` (hours): The minimum duration in hours that is considered a stop of interest (death or tag loss probable). Unit: `hours`.
- `Maximum stop diameter` (meters): Defined diameter that the animal has to stay in for the configured time for it to be considered stop. Unit: `meters`.
- `Display final stop only` (boolean): If only the last stop in a trajectory (that is, the most recent stop) should be displayed on the output map, in the case that more than one stop exist for a given individual. `True` or `False`.

### Null or error handling

**Setting `Minimum duration in hours`:** If no Minium duration is given (NULL), then a default duration of 120 hours (5 days) is set. 
**Setting `Maximum stop diameter`:** If no Maximum stop diameter is given, then a default diameter of 100 meters is set.
**Setting `Display final stop only`:** If no selection for Display final stop only is given, then a default value of `True` is set.

