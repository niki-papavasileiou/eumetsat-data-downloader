from pyproj import Proj
from pyresample import AreaDefinition


def calculate_aoi(
    name, proj, min_latitude, max_latitude, min_longitude, max_longitude, resolution
):
    # Calculate the center latitude and longitude
    lat_0 = (max_latitude + min_latitude) / 2
    lon_0 = (max_longitude + min_longitude) / 2

    # Define the projection using Proj
    p = Proj(proj=proj, lat_0=lat_0, lon_0=lon_0, ellps="WGS84")

    # Transform coordinates to projected space
    left, up = p(min_longitude, max_latitude)
    right, up = p(max_longitude, max_latitude)
    left, down = p(min_longitude, min_latitude)
    right, down = p(max_longitude, min_latitude)

    # Calculate area extent
    area_extent = (
        min(left, right),  # Lower-left X
        min(up, down),  # Lower-left Y
        max(left, right),  # Upper-right X
        max(up, down),  # Upper-right Y
    )

    # Calculate the dimensions of the area in pixels
    res = resolution * 1000  # Convert resolution to meters
    xsize = int(round((area_extent[2] - area_extent[0]) / res))
    ysize = int(round((area_extent[3] - area_extent[1]) / res))

    # Projection string for Satpy
    proj4_string = f"+proj={proj} +lat_0={lat_0} +lon_0={lon_0} +ellps=WGS84"

    # Create the AOI using pyresample's AreaDefinition
    area_def = AreaDefinition(
        area_id=name,
        description=name,
        proj_id=name,
        projection=proj4_string,
        width=xsize,
        height=ysize,
        area_extent=area_extent,
    )
    return area_def, xsize, ysize, area_extent, proj4_string
