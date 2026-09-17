import logging
import os

import eumdac

from functions.edit_data import uznip_and_edit_data
from settings import CONSUMER_KEY, CONSUMER_SECRET, DATA_DOWNLOADER_FOLDER
from functions.handle_files import (
    collection_folder_to_clear,
    load_downloaded_files,
    is_file_downloaded,
    save_downloaded_file,
)

# Bytes read from the Data Store per chunk. Small enough that Stop is noticed
# almost immediately, large enough not to slow the transfer down.
CHUNK_SIZE = 256 * 1024

# Seconds between real-time polling cycles.
POLL_INTERVAL_SECONDS = 60

COLLECTION_IDS = {
    "firerisk": "EO:EUM:DAT:0398",
    "cloud_mask": "EO:EUM:DAT:MSG:CLM",
    "IASI": "EO:EUM:DAT:METOP:IASSND02",
    "SEVIRI": "EO:EUM:DAT:MSG:HRSEVIRI",
    "FCI": "EO:EUM:DAT:0662",
    "FCI_LI": "EO:EUM:DAT:0691",
}


class StopRequested(Exception):
    """Raised inside a worker when the user presses Stop."""


def connect_to_datastore():
    credentials = (CONSUMER_KEY, CONSUMER_SECRET)
    token = eumdac.AccessToken(credentials)
    return eumdac.DataStore(token)


def _remove_partial(filename, logger):
    """Delete a half-written product so it is never mistaken for a complete one."""
    try:
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"Removed incomplete file {os.path.basename(filename)}.")
    except OSError as exc:
        logger.warning(f"Could not remove incomplete file {filename}: {exc}")


def _download_product(product, filename, logger, stop_event):
    """Stream one product to disk, checking stop_event between chunks.

    shutil.copyfileobj() cannot be interrupted: it returns only once the whole
    product has transferred, which for an FCI granule is minutes. Reading in
    chunks is what makes Stop responsive during a large download.
    """
    logger.info(f"Downloading product {product}...")
    # Guarantees the destination exists no matter which caller got here.
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    try:
        with product.open() as fsrc, open(filename, mode="wb") as fdst:
            while True:
                if stop_event.is_set():
                    raise StopRequested
                chunk = fsrc.read(CHUNK_SIZE)
                if not chunk:
                    break
                fdst.write(chunk)
    except StopRequested:
        _remove_partial(filename, logger)
        raise
    except Exception:
        _remove_partial(filename, logger)
        raise
    logger.info(f"Download of product {product} finished.")


def download_col_realtime(logger: logging.Logger, stop_event, selected_folder: str):
    """Poll every collection for its latest product until the user stops."""
    logger.info("Real-time data download started...")

    try:
        datastore = connect_to_datastore()
    except Exception as exc:
        logger.error(f"Could not connect to the EUMETSAT Data Store: {exc}")
        return

    collections = {
        "EO:EUM:DAT:0398": "firerisk",
        "EO:EUM:DAT:MSG:CLM": "cloud_mask",
        "EO:EUM:DAT:METOP:IASSND02": "IASI",
        "EO:EUM:DAT:MSG:HRSEVIRI": "SEVIRI",
        "EO:EUM:DAT:0662": "FCI",
        "EO:EUM:DAT:0691": "FCI_LI",
    }

    try:
        while not stop_event.is_set():
            # Reloaded each cycle so products saved during the previous cycle
            # are recognised as already downloaded.
            downloaded_files = load_downloaded_files()

            for col, folder_name in collections.items():
                if stop_event.is_set():
                    raise StopRequested

                try:
                    collection_folder = os.path.join(
                        DATA_DOWNLOADER_FOLDER, folder_name
                    )
                    os.makedirs(collection_folder, exist_ok=True)
                    collection_folder_to_clear(col, collection_folder)

                    selected_collection = datastore.get_collection(col)
                    product = selected_collection.search().first()

                    if not product:
                        logger.info(f"No product found for {folder_name}. Skipping.")
                        continue

                    filename = os.path.join(collection_folder, str(product))

                    if is_file_downloaded(filename, downloaded_files):
                        logger.info(f"File {filename} already downloaded. Skipping.")
                        continue

                    _download_product(product, filename, logger, stop_event)

                    uznip_and_edit_data(
                        selected_collection,
                        filename,
                        logger,
                        collection_folder,
                        product,
                        selected_folder,
                    )
                    save_downloaded_file(filename)

                    logger.info(
                        "Processing finished. Waiting for the next product...\n"
                    )

                except StopRequested:
                    raise
                except Exception as exc:
                    # One failing collection must not end the whole session.
                    logger.error(f"Error while handling {folder_name}: {exc}")
                    continue

            # Interruptible pause. time.sleep(60) would ignore Stop for a full
            # minute; wait() returns True the moment the flag is set.
            if stop_event.wait(POLL_INTERVAL_SECONDS):
                break

    except StopRequested:
        pass

    logger.info("Real-time download stopped.")


def download_col_custom(
    collection,
    from_date,
    to_date,
    logger: logging.Logger,
    stop_event,
    selected_folder,
):
    """Download every product in one collection over a date range, once."""
    logger.info(
        f"Custom data download for collection '{collection}' "
        f"from {from_date} to {to_date} started..."
    )

    collection_id = COLLECTION_IDS.get(collection)
    if not collection_id:
        logger.error(f"Invalid collection: {collection}")
        return

    try:
        datastore = connect_to_datastore()
        selected_col = datastore.get_collection(collection_id)
        products = list(selected_col.search(dtstart=from_date, dtend=to_date))
    except Exception as exc:
        logger.error(f"Could not query the EUMETSAT Data Store: {exc}")
        return

    if not products:
        logger.info("No products found for this collection and date range.")
        return

    total = len(products)
    logger.info(f"{total} product(s) found.")

    collection_folder = os.path.join(DATA_DOWNLOADER_FOLDER, collection)
    os.makedirs(collection_folder, exist_ok=True)
    downloaded_files = load_downloaded_files()

    try:
        for index, product in enumerate(products, start=1):
            if stop_event.is_set():
                raise StopRequested

            collection_folder_to_clear(str(selected_col), collection_folder)

            filename = os.path.join(collection_folder, str(product))

            if is_file_downloaded(filename, downloaded_files):
                logger.info(f"File {filename} already downloaded. Skipping.")
                continue

            logger.info(f"[{index}/{total}] Processing product...")
            _download_product(product, filename, logger, stop_event)

            uznip_and_edit_data(
                collection_id,
                filename,
                logger,
                collection_folder,
                product,
                selected_folder,
            )
            save_downloaded_file(filename)

            logger.info("Processing finished.\n")

    except StopRequested:
        logger.info("Download stopped by user.")
        return
    except Exception as exc:
        logger.error(f"Download failed: {exc}")
        return

    logger.info(f"Custom download complete. {total} product(s) processed.")
