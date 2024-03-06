import xml.etree.cElementTree as et
from functools import partial
from typing import Tuple

from ophyd import ADComponent as ADC
from ophyd import (
    AreaDetector,
    CamBase,
    Component,
    Device,
    EpicsSignal,
    HDF5Plugin,
    OverlayPlugin,
    ProcessPlugin,
    ROIPlugin,
    Signal,
    StatusBase,
)

from dodal.devices.areadetector.plugins.MXSC import MXSC
from dodal.devices.oav.grid_overlay import SnapshotWithGrid
from dodal.devices.oav.oav_errors import (
    OAVError_BeamPositionNotFound,
    OAVError_ZoomLevelNotFound,
)
from dodal.log import LOGGER

# GDA corrently assumes this aspect ratio for the OAV window size.
# For some beamline this doesn't affect anything as the actual OAV aspect ratio
# matches. Others need to take it into account to rescale the values stored in
# the configuration files.
DEFAULT_OAV_WINDOW = (1024, 768)


class ZoomController(Device):
    """
    Device to control the zoom level. This should be set like
        o = OAV(name="oav")
        oav.zoom_controller.set("1.0x")

    Note that changing the zoom may change the AD wiring on the associated OAV, as such
    you should wait on any zoom changs to finish before changing the OAV wiring.
    """

    percentage = Component(EpicsSignal, "ZOOMPOSCMD")

    # Level is the string description of the zoom level e.g. "1.0x"
    level = Component(EpicsSignal, "MP:SELECT", string=True)
    # Used by OAV to work out if we're changing the setpoint
    _level_sp = Component(Signal)

    zrst = Component(EpicsSignal, "MP:SELECT.ZRST")
    onst = Component(EpicsSignal, "MP:SELECT.ONST")
    twst = Component(EpicsSignal, "MP:SELECT.TWST")
    thst = Component(EpicsSignal, "MP:SELECT.THST")
    frst = Component(EpicsSignal, "MP:SELECT.FRST")
    fvst = Component(EpicsSignal, "MP:SELECT.FVST")
    sxst = Component(EpicsSignal, "MP:SELECT.SXST")

    def set_flatfield_on_zoom_level_one(self, value):
        flat_applied = self.parent.proc.port_name.get()
        no_flat_applied = self.parent.cam.port_name.get()

        input_plugin = flat_applied if value == "1.0x" else no_flat_applied

        flat_field_status = self.parent.mxsc.input_plugin.set(input_plugin)
        return flat_field_status & self.parent.snapshot.input_plugin.set(input_plugin)

    @property
    def allowed_zoom_levels(self):
        return [
            self.zrst.get(),
            self.onst.get(),
            self.twst.get(),
            self.thst.get(),
            self.frst.get(),
            self.fvst.get(),
            self.sxst.get(),
        ]

    def set(self, level_to_set: str) -> StatusBase:
        return_status = self._level_sp.set(level_to_set)
        return_status &= self.level.set(level_to_set)
        return_status &= self.set_flatfield_on_zoom_level_one(level_to_set)
        return return_status


class OAVConfigParams:
    """
    The OAV parameters which may update depending on settings such as the zoom level.
    """

    def __init__(
        self,
        zoom_params_file,
        display_config,
    ):
        self.zoom_params_file: str = zoom_params_file
        self.display_config: str = display_config

    def update_on_zoom(self, value, xsize, ysize, *args, **kwargs):
        xsize, ysize = int(xsize), int(ysize)
        if isinstance(value, str) and value.endswith("x"):
            value = value.strip("x")
        zoom = float(value)
        self.load_microns_per_pixel(zoom, xsize, ysize)
        self.beam_centre_i, self.beam_centre_j = self.get_beam_position_from_zoom(
            zoom, xsize, ysize
        )

    def load_microns_per_pixel(self, zoom: float, xsize: int, ysize: int) -> None:
        """
        Loads the microns per x pixel and y pixel for a given zoom level. These are
        currently generated by GDA, though hyperion could generate them in future.
        """
        tree = et.parse(self.zoom_params_file)
        self.micronsPerXPixel = self.micronsPerYPixel = None
        root = tree.getroot()
        levels = root.findall(".//zoomLevel")
        for node in levels:
            if float(node.find("level").text) == zoom:
                self.micronsPerXPixel = (
                    float(node.find("micronsPerXPixel").text)
                    * DEFAULT_OAV_WINDOW[0]
                    / xsize
                )
                self.micronsPerYPixel = (
                    float(node.find("micronsPerYPixel").text)
                    * DEFAULT_OAV_WINDOW[1]
                    / ysize
                )
        if self.micronsPerXPixel is None or self.micronsPerYPixel is None:
            raise OAVError_ZoomLevelNotFound(
                f"""
                Could not find the micronsPer[X,Y]Pixel parameters in
                {self.zoom_params_file} for zoom level {zoom}.
                """
            )

    def get_beam_position_from_zoom(
        self, zoom: float, xsize: int, ysize: int
    ) -> Tuple[int, int]:
        """
        Extracts the beam location in pixels `xCentre` `yCentre`, for a requested zoom \
        level. The beam location is manually inputted by the beamline operator on GDA \
        by clicking where on screen a scintillator lights up, and stored in the \
        display.configuration file.
        """
        crosshair_x_line = None
        crosshair_y_line = None
        with open(self.display_config, "r") as f:
            file_lines = f.readlines()
            for i in range(len(file_lines)):
                if file_lines[i].startswith("zoomLevel = " + str(zoom)):
                    crosshair_x_line = file_lines[i + 1]
                    crosshair_y_line = file_lines[i + 2]
                    break

        if crosshair_x_line is None or crosshair_y_line is None:
            raise OAVError_BeamPositionNotFound(
                f"Could not extract beam position at zoom level {zoom}"
            )

        beam_centre_i = (
            int(crosshair_x_line.split(" = ")[1]) * xsize / DEFAULT_OAV_WINDOW[0]
        )
        beam_centre_j = (
            int(crosshair_y_line.split(" = ")[1]) * ysize / DEFAULT_OAV_WINDOW[1]
        )
        LOGGER.info(f"Beam centre: {beam_centre_i, beam_centre_j}")
        return int(beam_centre_i), int(beam_centre_j)

    def calculate_beam_distance(
        self, horizontal_pixels: int, vertical_pixels: int
    ) -> Tuple[int, int]:
        """
        Calculates the distance between the beam centre and the given (horizontal, vertical).

        Args:
            horizontal_pixels (int): The x (camera coordinates) value in pixels.
            vertical_pixels (int): The y (camera coordinates) value in pixels.
        Returns:
            The distance between the beam centre and the (horizontal, vertical) point in pixels as a tuple
            (horizontal_distance, vertical_distance).
        """

        return (
            self.beam_centre_i - horizontal_pixels,
            self.beam_centre_j - vertical_pixels,
        )


class OAV(AreaDetector):
    cam = ADC(CamBase, "-DI-OAV-01:CAM:")
    roi = ADC(ROIPlugin, "-DI-OAV-01:ROI:")
    proc = ADC(ProcessPlugin, "-DI-OAV-01:PROC:")
    over = ADC(OverlayPlugin, "-DI-OAV-01:OVER:")
    tiff = ADC(OverlayPlugin, "-DI-OAV-01:TIFF:")
    hdf5 = ADC(HDF5Plugin, "-DI-OAV-01:HDF5:")
    snapshot = Component(SnapshotWithGrid, "-DI-OAV-01:MJPG:")
    mxsc = ADC(MXSC, "-DI-OAV-01:MXSC:")
    zoom_controller = Component(ZoomController, "-EA-OAV-01:FZOOM:")

    def __init__(self, *args, params: OAVConfigParams, **kwargs):
        super().__init__(*args, **kwargs)
        self.parameters = params
        self.subscription_id = None

    def wait_for_connection(self, all_signals=False, timeout=2):
        connected = super().wait_for_connection(all_signals, timeout)
        x = self.snapshot.x_size.get()
        y = self.snapshot.y_size.get()

        cb = partial(self.parameters.update_on_zoom, xsize=x, ysize=y)

        if self.subscription_id is not None:
            self.zoom_controller.level.unsubscribe(self.subscription_id)
        self.subscription_id = self.zoom_controller.level.subscribe(cb)

        return connected
