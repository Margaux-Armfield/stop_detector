# Armfield Detect Stationarity in GeoTags

MoveApps

Github repository: *github.com/yourAccount/Name-of-App* *(the link to the repository where the code of the app can be found must be provided)*

## SDK

As an **App developer** you should have a look into the [developer README document](developer_README.md). 
*Please delete this section for your final app documentation*

## Description
*Enter here the short description of the App that might also be used when filling out the description at submission of the App to Moveapps. This text is directly presented to Users that look through the list of Apps when compiling Workflows.*

## Documentation
*Enter here a detailed description of your App. What is it intended to be used for. Which steps of analyses are performed and how. Please be explicit about any detail that is important for use and understanding of the App and its outcomes.*

### Input data

MovingPandas TrajectoryCollection in Movebank format

### Output data

MovingPandas TrajectoryCollection in Movebank format

### Artefacts
*If the App creates artefacts (e.g. csv, pdf, jpeg, shapefiles, etc), please list them here and describe each.*

*Example:* `rest_overview.csv`: csv-file with Table of all rest site properties

### Settings 
*Please list and define all settings/parameters that the App requires to be set, if necessary including their unit.*

*Example:* `Radius of resting site` (radius): Defined radius the animal has to stay in for a given duration of time for it to be considered resting site. Unit: `metres`.

### Null or error handling
*Please indicate for each setting/parameter as well as the input data which behaviour the App is supposed to show in case of errors or NULL values/input. Please also add notes of possible errors that can happen if settings are improperly set and any other important information that you find the user should be aware of.*

*Example:* **Setting `radius`:** If no radius AND no duration are given, the input data set is returned with a warning. If no radius is given (NULL), but a duration is defined then a default radius of 1000m = 1km is set. 
