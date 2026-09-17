import glob
import logging
import os
import re
import zipfile
import time

import numpy as np
import pandas as pd
import satpy
from netCDF4 import Dataset
from pyproj import Transformer
from satpy import find_files_and_readers
from satpy.scene import Scene

from functions.projection import calculate_aoi


def edit_seviri(logger: logging, filename: str, selected_folder: str):
    logger.info(f"Processing SEVIRI data from {filename}...")

    data_files = glob.glob("MyData/SEVIRI/*.nat")
    data_files.sort()
    first_file = [data_files[0]]

    scn = satpy.Scene(reader="seviri_l1b_native", filenames=first_file)
    bands = ["IR_087", "IR_108", "IR_120", "WV_062", "WV_073", "IR_039"]

    for band in bands:
        scn.load([band], upper_right_corner="NE")

        # Define parameters for the AOI
        name = "AOI"
        proj = "merc"  # Replace with your desired projection
        min_latitude = 19.0
        max_latitude = 28.25
        min_longitude = 34.8
        max_longitude = 41.8
        resolution = 3.0  # Resolution in kilometers

        # Calculate the AOI
        AOI, xsize, ysize, area_extent, proj4_string = calculate_aoi(
            name,
            proj,
            min_latitude,
            max_latitude,
            min_longitude,
            max_longitude,
            resolution,
        )

        # Resample the scene to the AOI
        scn_resample = scn.resample(AOI)

        match = re.match(
            r"MSG(\d+)-\S+-\S+-(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})", filename
        )
        if match:
            msg_number, year, month, day, hour, minute = match.groups()
            output_filename = f"MSG__{band}_{year}_{month}_{day}_{hour}{minute}.csv"

            # Access the resampled data
            data_array = scn_resample[band]

            # Transform x, y coordinates to latitude and longitude
            source_crs = AOI.proj_dict  # Source CRS from AOI
            target_crs = "EPSG:4326"  # Target CRS (WGS84)

            # Create a transformer
            transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)

            # Extract the 'x' (easting) and 'y' (northing) coordinates
            x_coords = data_array["x"].values
            y_coords = data_array["y"].values

            # Create a 2D grid of x and y coordinates using numpy.meshgrid
            x_grid, y_grid = np.meshgrid(x_coords, y_coords)

            # Apply the transformation to the coordinate grid
            lon_coords, lat_coords = transformer.transform(x_grid, y_grid)

            # Add latitude and longitude as coordinates to the data_array
            data_array = data_array.assign_coords(
                lon=(("y", "x"), lon_coords), lat=(("y", "x"), lat_coords)
            )

            data_array.name = "values"
            df = data_array.to_dataframe().reset_index()
            df = df[["lat", "lon", "values"]]
            df = df.pivot(index="lon", columns="lat", values="values")

            # Save the result to CSV
            file_path = os.path.join(selected_folder, output_filename)
            df.to_csv(file_path)
    time.sleep(10)


def edit_fci(logger: logging, filename: str, selected_folder: str):
    logger.info(f"Processing FCI data from {filename}...")

    path_to_data = glob.glob("MyData/FCI/*.nc")

    # Load the data
    files = find_files_and_readers(base_dir="MyData/FCI", reader="fci_l1c_nc")
    scn = Scene(filenames=files)
    bands = ["ir_105", "ir_87", "ir_123", "wv_63", "wv_73", "ir_38"]
    original_filename = path_to_data[0]

    for band in bands:
        scn.load([band])

        # Define parameters for the AOI
        name = "AOI"
        proj = "merc"  # Replace with your desired projection
        min_latitude = 19.0
        max_latitude = 28.25
        min_longitude = 34.8
        max_longitude = 41.8
        resolution = 1.0  # Resolution in kilometers

        # Calculate the AOI
        AOI, xsize, ysize, area_extent, proj4_string = calculate_aoi(
            name,
            proj,
            min_latitude,
            max_latitude,
            min_longitude,
            max_longitude,
            resolution,
        )

        # Resample the scene to the AOI
        scn_resample = scn.resample(AOI)

        full_path = original_filename
        base_filename = os.path.basename(full_path)

        match = re.match(r".*FCI.*_(\d{14})_(\d{14})", base_filename)
        if match:
            start_date, end_date = match.groups()
            output_filename = f"FCI_date_{start_date}_{end_date}_{band}.csv"

            # Access the resampled data
            data_array = scn_resample[band]

            # Transform x, y coordinates to latitude and longitude
            source_crs = AOI.proj_dict  # Source CRS from AOI
            target_crs = "EPSG:4326"  # Target CRS (WGS84)

            # Create a transformer
            transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)

            # Extract the 'x' (easting) and 'y' (northing) coordinates
            x_coords = data_array["x"].values
            y_coords = data_array["y"].values

            # Create a 2D grid of x and y coordinates using numpy.meshgrid
            x_grid, y_grid = np.meshgrid(x_coords, y_coords)

            # Apply the transformation to the coordinate grid
            lon_coords, lat_coords = transformer.transform(x_grid, y_grid)

            # Add latitude and longitude as coordinates to the data_array
            data_array = data_array.assign_coords(
                lon=(("y", "x"), lon_coords), lat=(("y", "x"), lat_coords)
            )

            data_array.name = "values"
            df = data_array.to_dataframe().reset_index()
            df = df[["lat", "lon", "values"]]
            df = df.pivot(index="lon", columns="lat", values="values")
            file_path = os.path.join(selected_folder, output_filename)
            df.to_csv(file_path)


def edit_fci_light(selected_folder: str):
    file_path = glob.glob("MyData\FCI_LI\*0001.nc")
    filename = os.path.basename(file_path[0])  # Get the filename from the path
    parts = filename.split("_")
    date_str = parts[4]
    new_filename = f"FCI_lightning_{date_str}.csv"

    # Open the file
    with Dataset(file_path[0], mode="r") as ds:
        # Extract variables
        flash_time = ds.variables["flash_time"][:]
        latitude = ds.variables["latitude"][:]
        longitude = ds.variables["longitude"][:]
        flash_id = ds.variables["flash_id"][:]
        number_of_events = ds.variables["number_of_events"][:]
        number_of_groups = ds.variables["number_of_groups"][:]
        flash_duration = ds.variables["flash_duration"][:]
        flash_footprint = ds.variables["flash_footprint"][:]
        radiance = ds.variables["radiance"][:]

        # Create a Pandas DataFrame
        data = {
            "flash_time": flash_time,
            "latitude": latitude,
            "longitude": longitude,
            "flash_id": flash_id,
            "radiance": radiance,
            "number_of_events": number_of_events,
            "number_of_groups": number_of_groups,
            "flash_duration": flash_duration,
            "flash_footprint": flash_footprint,
        }
        df = pd.DataFrame(data)
        df["flash_time"] = pd.to_datetime(df["flash_time"])
        file_path = os.path.join(selected_folder, new_filename)
        df.to_csv(file_path)


def uznip_and_edit_data(
    selected_collection: str,
    filename: str,
    logger: logging,
    collection_folder: str,
    product,
    selected_folder: str,
):
    if str(selected_collection) in [
        "EO:EUM:DAT:MSG:HRSEVIRI",
        "EO:EUM:DAT:0662",
        "EO:EUM:DAT:0691",
    ]:

        downloaded_file = filename
        if zipfile.is_zipfile(downloaded_file):
            with zipfile.ZipFile(downloaded_file, "r") as zip_ref:
                zip_ref.extractall(collection_folder)
                logger.info(f"Unzipped contents of {downloaded_file}.")

                # Call the correct function based on selected_collection
                if str(selected_collection) == "EO:EUM:DAT:MSG:HRSEVIRI":
                    edit_seviri(
                        logger=logger,
                        filename=str(product),
                        selected_folder=selected_folder,
                    )
                elif str(selected_collection) == "EO:EUM:DAT:0662":
                    edit_fci(
                        logger=logger,
                        filename=str(product),
                        selected_folder=selected_folder,
                    )
                elif str(selected_collection) == "EO:EUM:DAT:0691":
                    edit_fci_light(selected_folder)
