import logging
import os
import sys
import threading
import time
import warnings

from PyQt5.QtCore import QDate, QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from functions.downloaders import download_col_realtime, download_col_custom

warnings.filterwarnings("ignore")
warnings.simplefilter(action="ignore", category=RuntimeWarning)

APP_NAME = "DATA DOWNLOADER"
APP_SUBTITLE = "METEOSAT Product Retrieval System"
APP_VERSION = "v1.0"

# How long to wait after a stop request before warning that the worker
# is not checking stop_event.
STOP_GRACE_SECONDS = 15

STYLESHEET = """
/* ---------- Base: classic grey workstation look ---------- */
QWidget {
    background-color: #d4d0c8;
    color: #000000;
    font-family: "Verdana", "Tahoma", "DejaVu Sans", sans-serif;
    font-size: 11px;
}

/* ---------- Title banner ---------- */
QFrame#banner {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                      stop:0 #0a246a, stop:1 #3a6ea5);
    border: 1px solid #000033;
}
QLabel#bannerTitle {
    background: transparent;
    color: #ffffff;
    font-family: "Georgia", "Times New Roman", serif;
    font-size: 18px;
    font-weight: bold;
    letter-spacing: 2px;
}
QLabel#bannerSub {
    background: transparent;
    color: #c8d8ff;
    font-style: italic;
    font-size: 11px;
}
QLabel#bannerVersion {
    background: transparent;
    color: #ffffff;
    font-family: "Courier New", monospace;
    font-size: 11px;
}

/* ---------- Group boxes (etched frames) ---------- */
QGroupBox {
    border: 1px solid #808080;
    border-top-color: #808080;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: #0a246a;
}

/* ---------- Inputs (sunken white fields) ---------- */
QLineEdit, QComboBox, QDateEdit {
    background-color: #ffffff;
    border: 2px inset #a0a0a0;
    padding: 2px 4px;
    min-height: 18px;
    font-weight: normal;
}
QLineEdit:read-only {
    background-color: #f4f3ee;
    font-family: "Courier New", monospace;
}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled {
    background-color: #e4e2dc;
    color: #808080;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    selection-background-color: #0a246a;
    selection-color: #ffffff;
    border: 1px solid #000000;
}

/* ---------- Buttons (raised bevel) ---------- */
QPushButton {
    background-color: #d4d0c8;
    border: 2px outset #ffffff;
    border-right-color: #404040;
    border-bottom-color: #404040;
    padding: 4px 16px;
    min-width: 80px;
    min-height: 20px;
    font-weight: normal;
}
QPushButton:hover {
    background-color: #e0ddd6;
}
QPushButton:pressed {
    border: 2px inset #404040;
    border-right-color: #ffffff;
    border-bottom-color: #ffffff;
    padding: 5px 15px 3px 17px;
}
QPushButton:disabled {
    color: #808080;
}
QPushButton#primary {
    font-weight: bold;
}
QPushButton:focus {
    outline: 1px dotted #000000;
}

/* ---------- Log console ---------- */
QTextEdit#console {
    background-color: #ffffff;
    color: #000000;
    border: 2px inset #a0a0a0;
    font-family: "Courier New", "Consolas", "DejaVu Sans Mono", monospace;
    font-size: 11px;
    font-weight: normal;
    selection-background-color: #0a246a;
}

/* ---------- Status bar ---------- */
QFrame#statusBar {
    border-top: 1px solid #808080;
}
QLabel#statusCell {
    border: 1px inset #a0a0a0;
    padding: 1px 6px;
    font-family: "Courier New", monospace;
}
QLabel#indicatorIdle {
    background-color: #808080; border: 1px solid #404040;
    min-width: 10px; max-width: 10px; min-height: 10px; max-height: 10px;
}
QLabel#indicatorBusy {
    background-color: #00c000; border: 1px solid #004000;
    min-width: 10px; max-width: 10px; min-height: 10px; max-height: 10px;
}

/* ---------- Calendar popup ---------- */
QCalendarWidget QWidget#qt_calendar_navigationbar {
    background-color: #0a246a;
}
QCalendarWidget QToolButton {
    color: #ffffff;
    background-color: #0a246a;
    border: none;
    font-weight: bold;
    padding: 2px 6px;
}
QCalendarWidget QAbstractItemView {
    background-color: #ffffff;
    color: #000000;
    selection-background-color: #0a246a;
    selection-color: #ffffff;
}
"""


class LogEmitter(QObject):
    message = pyqtSignal(str)


class QTextEditLogger(logging.Handler):
    """Thread-safe: records from worker threads are delivered via a Qt signal."""

    def __init__(self, textbox):
        super().__init__()
        self.textbox = textbox
        self.emitter = LogEmitter()
        self.emitter.message.connect(self._append)

    def emit(self, record):
        self.emitter.message.emit(self.format(record))

    def _append(self, msg):
        self.textbox.moveCursor(QTextCursor.End)
        self.textbox.insertPlainText(msg + "\n")
        self.textbox.moveCursor(QTextCursor.End)


class DownloaderApp(QWidget):
    def __init__(self):
        super().__init__()

        self.downloading = False
        self.stopping = False
        self.stop_deadline = None
        self.stop_event = threading.Event()
        self.collected_data_thread = None
        self.selected_folder = ""

        self.init_ui()
        self.setup_logging()

        # Watch the worker thread so the UI resets when a download ends on its own
        self.watch_timer = QTimer(self)
        self.watch_timer.timeout.connect(self.check_thread)
        self.watch_timer.start(500)

        self.logger.info("Application started. Select an output directory to begin.")

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        self.setWindowTitle(f"{APP_NAME.title()} {APP_VERSION}")
        self.setStyleSheet(STYLESHEET)
        self.resize(720, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(6)

        root.addWidget(self.build_banner())

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.build_parameters_group(), 3)
        top.addWidget(self.build_control_group(), 2)

        root.addWidget(self.build_output_group())
        root.addLayout(top)
        root.addWidget(self.build_log_group(), 1)
        root.addWidget(self.build_status_bar())

        self.update_controls(self.mode_dropdown.currentIndex())

    def build_banner(self):
        banner = QFrame()
        banner.setObjectName("banner")
        lay = QHBoxLayout(banner)
        lay.setContentsMargins(12, 8, 12, 8)

        text = QVBoxLayout()
        text.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("bannerTitle")
        sub = QLabel(APP_SUBTITLE)
        sub.setObjectName("bannerSub")
        text.addWidget(title)
        text.addWidget(sub)

        version = QLabel(APP_VERSION)
        version.setObjectName("bannerVersion")
        version.setAlignment(Qt.AlignRight | Qt.AlignBottom)

        lay.addLayout(text)
        lay.addStretch()
        lay.addWidget(version)
        return banner

    def build_output_group(self):
        group = QGroupBox("1. Output Directory")
        lay = QHBoxLayout(group)

        self.folder_field = QLineEdit()
        self.folder_field.setReadOnly(True)
        self.folder_field.setPlaceholderText("(no directory selected)")

        self.btn_select_folder = QPushButton("Browse...")
        self.btn_select_folder.clicked.connect(self.select_folder)

        lay.addWidget(QLabel("Path:"))
        lay.addWidget(self.folder_field, 1)
        lay.addWidget(self.btn_select_folder)
        return group

    def build_parameters_group(self):
        group = QGroupBox("2. Acquisition Parameters")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.mode_dropdown = QComboBox()
        self.mode_dropdown.addItems(["Real-time", "Custom"])
        self.mode_dropdown.currentIndexChanged.connect(self.update_controls)

        self.collection_dropdown = QComboBox()
        self.collection_dropdown.addItems(
            ["firerisk", "cloud_mask", "SEVIRI", "IASI", "FCI", "FCI_LI"]
        )

        self.from_date_edit = QDateEdit()
        self.from_date_edit.setCalendarPopup(True)
        self.from_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.from_date_edit.setDate(QDate.currentDate().addDays(-7))

        self.to_date_edit = QDateEdit()
        self.to_date_edit.setCalendarPopup(True)
        self.to_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.to_date_edit.setDate(QDate.currentDate())

        form.addRow("Mode:", self.mode_dropdown)
        form.addRow("Collection:", self.collection_dropdown)
        form.addRow("Start date:", self.from_date_edit)
        form.addRow("End date:", self.to_date_edit)
        return group

    def build_control_group(self):
        group = QGroupBox("3. Run Control")
        lay = QGridLayout(group)
        lay.setVerticalSpacing(8)

        self.btn_download = QPushButton("Start Download")
        self.btn_download.setObjectName("primary")
        self.btn_download.clicked.connect(self.download_data)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.clicked.connect(self.stop_download)
        self.btn_stop.setEnabled(False)

        btn_clear = QPushButton("Clear Log")
        btn_clear.clicked.connect(lambda: self.textbox.clear())

        self.mode_hint = QLabel()
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setStyleSheet("font-weight: normal; color: #404040;")

        lay.addWidget(self.btn_download, 0, 0, 1, 2)
        lay.addWidget(self.btn_stop, 1, 0)
        lay.addWidget(btn_clear, 1, 1)
        lay.addWidget(self.mode_hint, 2, 0, 1, 2)
        lay.setRowStretch(3, 1)
        return group

    def build_log_group(self):
        group = QGroupBox("Session Log")
        lay = QVBoxLayout(group)
        self.textbox = QTextEdit()
        self.textbox.setObjectName("console")
        self.textbox.setReadOnly(True)
        self.textbox.setLineWrapMode(QTextEdit.NoWrap)
        lay.addWidget(self.textbox)
        return group

    def build_status_bar(self):
        bar = QFrame()
        bar.setObjectName("statusBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)

        self.indicator = QLabel()
        self.indicator.setObjectName("indicatorIdle")

        self.status_label = QLabel("READY")
        self.status_label.setObjectName("statusCell")

        self.status_mode = QLabel("MODE: REAL-TIME")
        self.status_mode.setObjectName("statusCell")

        lay.addWidget(self.indicator)
        lay.addWidget(self.status_label, 1)
        lay.addWidget(self.status_mode)
        return bar

    def set_status(self, text, busy):
        self.status_label.setText(text)
        self.indicator.setObjectName("indicatorBusy" if busy else "indicatorIdle")
        self.indicator.style().unpolish(self.indicator)
        self.indicator.style().polish(self.indicator)

    # ------------------------------------------------------------- logic
    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.selected_folder = folder
            self.folder_field.setText(folder)
            self.logger.info(f"Selected folder: {self.selected_folder}")

    def setup_logging(self):
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)
        fmt = logging.Formatter(
            "%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        file_handler = logging.FileHandler("app.log", mode="w")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(fmt)

        self.gui_handler = QTextEditLogger(self.textbox)
        self.gui_handler.setLevel(logging.INFO)
        self.gui_handler.setFormatter(fmt)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(self.gui_handler)

    def update_controls(self, index):
        custom = index == 1
        self.collection_dropdown.setEnabled(custom)
        self.from_date_edit.setEnabled(custom)
        self.to_date_edit.setEnabled(custom)
        if custom:
            self.mode_hint.setText("Custom: fetch one collection over a date range.")
            self.status_mode.setText("MODE: CUSTOM")
        else:
            self.mode_hint.setText("Real-time: continuously fetch the latest products.")
            self.status_mode.setText("MODE: REAL-TIME")

    def download_data(self):
        if not self.selected_folder:
            self.logger.warning("No output directory selected.")
            return
        if self.mode_dropdown.currentIndex() == 0:
            self.start_realtime_download()
        else:
            self.start_custom_download()

    def _begin(self):
        """Prepare for a new run. Returns False if a previous run is still alive."""
        if self.collected_data_thread and self.collected_data_thread.is_alive():
            self.logger.warning(
                "Previous download is still shutting down. Please wait for it to finish."
            )
            return False

        # A fresh Event per run, rather than clearing the old one: a worker that
        # is still winding down keeps seeing its own flag set.
        self.stop_event = threading.Event()
        self.downloading = True
        self.stopping = False
        self.stop_deadline = None
        self.btn_stop.setEnabled(True)
        self.btn_download.setEnabled(False)
        self.mode_dropdown.setEnabled(False)
        self.set_status("DOWNLOADING...", busy=True)
        return True

    def start_realtime_download(self):
        if not self.downloading:
            if not self._begin():
                return
            self.collected_data_thread = threading.Thread(
                target=download_col_realtime,
                args=(self.logger, self.stop_event, self.selected_folder),
                daemon=True,
            )
            self.collected_data_thread.start()

    def start_custom_download(self):
        if not self.downloading:
            if not self._begin():
                return
            selected_collection = self.collection_dropdown.currentText()
            from_date = self.from_date_edit.date().toString("yyyy-MM-dd")
            to_date = self.to_date_edit.date().toString("yyyy-MM-dd")

            self.collected_data_thread = threading.Thread(
                target=download_col_custom,
                args=(
                    selected_collection,
                    from_date,
                    to_date,
                    self.logger,
                    self.stop_event,
                    self.selected_folder,
                ),
                daemon=True,
            )
            self.collected_data_thread.start()

    def stop_download(self):
        if not (self.collected_data_thread and self.collected_data_thread.is_alive()):
            self._finish()
            return

        # Signal only. Never join() on the GUI thread: that freezes the window,
        # and the UI must not report READY while the worker is still running.
        self.stop_event.set()
        self.stopping = True
        self.stop_deadline = time.monotonic() + STOP_GRACE_SECONDS
        self.btn_stop.setEnabled(False)
        self.set_status("STOPPING...", busy=True)
        self.logger.info(
            "Stop requested. Waiting for the current operation to finish..."
        )

    def check_thread(self):
        """Polled twice a second: reflects what the worker thread is actually doing."""
        alive = bool(
            self.collected_data_thread and self.collected_data_thread.is_alive()
        )
        if not self.downloading:
            return

        if not alive:
            self.logger.info(
                "Download stopped." if self.stopping else "Download finished."
            )
            self._finish()
            return

        if (
            self.stopping
            and self.stop_deadline
            and time.monotonic() > self.stop_deadline
        ):
            self.stop_deadline = None  # warn once per stop request
            self.logger.warning(
                "Worker has not responded to the stop request after %d seconds. "
                "Close the window to force-quit.",
                STOP_GRACE_SECONDS,
            )
            self.set_status("STOPPING... (NOT RESPONDING)", busy=True)

    def _finish(self):
        self.downloading = False
        self.stopping = False
        self.stop_deadline = None
        self.btn_stop.setEnabled(False)
        self.btn_download.setEnabled(True)
        self.mode_dropdown.setEnabled(True)
        self.set_status("READY", busy=False)

    def closeEvent(self, event):
        """Forcefully kill all running threads and exit the application."""
        self.stop_event.set()
        if self.collected_data_thread and self.collected_data_thread.is_alive():
            self.collected_data_thread.join(timeout=2)
        os._exit(0)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Windows")  # classic bevelled base style
    downloader = DownloaderApp()
    downloader.show()
    sys.exit(app.exec_())
