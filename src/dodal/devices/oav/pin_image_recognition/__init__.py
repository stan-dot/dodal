import asyncio
import time

import numpy as np
from ophyd_async.core import (
    Array1D,
    AsyncStatus,
    StandardReadable,
    StandardReadableFormat,
    observe_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.epics.core import epics_signal_r

from dodal.devices.oav.pin_image_recognition.utils import (
    ARRAY_PROCESSING_FUNCTIONS_MAP,
    MxSampleDetect,
    SampleLocation,
    ScanDirections,
    identity,
)
from dodal.log import LOGGER

# Tip position in x, y pixel coordinates
Tip = Array1D[np.int32]


class InvalidPinException(Exception):
    pass


class PinTipDetection(StandardReadable):
    """
    A device which will read from an on-axis view and calculate the location of the
    pin-tip (in pixels) of that frame.

    Used for pin tip centring workflow.

    Note that if the tip of the sample is off-screen, this class will return the tip as
    the "edge" of the image.

    If no tip is found it will return {INVALID_POSITION}. However, it will also
    occasionally give incorrect data. Therefore, it is recommended that you trigger
    this device, which will attempt to find a pin within {validity_timeout} seconds if
    no tip is found after this time it will not error but instead return {INVALID_POSITION}.
    """

    INVALID_POSITION = np.array([np.iinfo(np.int32).min, np.iinfo(np.int32).min])

    def __init__(self, prefix: str, name: str = ""):
        self._prefix: str = prefix
        self._name = name

        self.triggered_tip, self._tip_setter = soft_signal_r_and_setter(
            Tip, name="triggered_tip"
        )
        self.triggered_top_edge, self._top_edge_setter = soft_signal_r_and_setter(
            Array1D[np.int32], name="triggered_top_edge"
        )
        self.triggered_bottom_edge, self._bottom_edge_setter = soft_signal_r_and_setter(
            Array1D[np.int32], name="triggered_bottom_edge"
        )
        self.array_data = epics_signal_r(np.ndarray, f"pva://{prefix}PVA:ARRAY")

        # Soft parameters for pin-tip detection.
        self.preprocess_operation = soft_signal_rw(int, 10, name="preprocess")
        self.preprocess_ksize = soft_signal_rw(int, 5, name="preprocess_ksize")
        self.preprocess_iterations = soft_signal_rw(
            int, 5, name="preprocess_iterations"
        )
        self.canny_upper_threshold = soft_signal_rw(int, 100, name="canny_upper")
        self.canny_lower_threshold = soft_signal_rw(int, 50, name="canny_lower")
        self.close_ksize = soft_signal_rw(int, 5, name="close_ksize")
        self.close_iterations = soft_signal_rw(int, 5, name="close_iterations")
        self.scan_direction = soft_signal_rw(
            int, ScanDirections.FORWARD.value, name="scan_direction"
        )
        self.min_tip_height = soft_signal_rw(int, 5, name="min_tip_height")
        self.validity_timeout = soft_signal_rw(float, 5.0, name="validity_timeout")

        self.add_readables(
            [
                self.triggered_tip,
                self.triggered_top_edge,
                self.triggered_bottom_edge,
            ],
            format=StandardReadableFormat.HINTED_SIGNAL,
        )

        super().__init__(name=name)

    def _set_triggered_values(self, results: SampleLocation):
        if results.tip_x is None or results.tip_y is None:
            raise InvalidPinException
        else:
            tip = np.array([results.tip_x, results.tip_y])
            self._tip_setter(tip)
        self._top_edge_setter(results.edge_top)
        self._bottom_edge_setter(results.edge_bottom)

    async def _get_tip_and_edge_data(self, array_data: np.ndarray) -> SampleLocation:
        """
        Gets the location of the pin tip and the top and bottom edges.
        """
        preprocess_key = await self.preprocess_operation.get_value()
        preprocess_iter = await self.preprocess_iterations.get_value()
        preprocess_ksize = await self.preprocess_ksize.get_value()

        try:
            preprocess_func = ARRAY_PROCESSING_FUNCTIONS_MAP[preprocess_key](
                iter=preprocess_iter, ksize=preprocess_ksize
            )
        except KeyError:
            LOGGER.error("Invalid preprocessing function, using identity")
            preprocess_func = identity()

        direction = (
            ScanDirections.FORWARD
            if await self.scan_direction.get_value() == 0
            else ScanDirections.REVERSE
        )

        sample_detection = MxSampleDetect(
            preprocess=preprocess_func,
            canny_lower=await self.canny_lower_threshold.get_value(),
            canny_upper=await self.canny_upper_threshold.get_value(),
            close_ksize=await self.close_ksize.get_value(),
            close_iterations=await self.close_iterations.get_value(),
            scan_direction=direction,
            min_tip_height=await self.min_tip_height.get_value(),
        )

        start_time = time.time()
        location = sample_detection.processArray(array_data)
        end_time = time.time()
        LOGGER.debug(
            f"Sample location detection took {(end_time - start_time) * 1000.0}ms"
        )
        return location

    @AsyncStatus.wrap
    async def trigger(self):
        async def _set_triggered_tip():
            """Monitors the camera data and updates the triggered_tip signal.

            If a tip is found it will update the signal and stop monitoring
            If no tip is found it will retry with the next monitored value
            This loop will serve as a good example of using 'observe_value' in the ophyd_async documentation
            """
            async for value in observe_value(self.array_data):
                try:
                    location = await self._get_tip_and_edge_data(value)
                    self._set_triggered_values(location)
                except Exception as e:
                    LOGGER.warning(
                        f"Failed to detect pin-tip location, will retry with next image: {e}"
                    )
                else:
                    return

        try:
            await asyncio.wait_for(
                _set_triggered_tip(), timeout=await self.validity_timeout.get_value()
            )
        except asyncio.exceptions.TimeoutError:
            LOGGER.error(
                f"No tip found in {await self.validity_timeout.get_value()} seconds."
            )
            self._tip_setter(self.INVALID_POSITION)
            self._bottom_edge_setter(np.array([]))
            self._top_edge_setter(np.array([]))
