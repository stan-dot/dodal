from unittest.mock import MagicMock

import pytest
from ophyd.sim import make_fake_device
from ophyd.status import StatusBase

from dodal.devices.aperturescatterguard import (
    ApertureFiveDimensionalLocation,
    AperturePositions,
    ApertureScatterguard,
    InvalidApertureMove,
    SingleAperturePosition,
)

from .conftest import patch_motor


@pytest.fixture
def ap_sg():
    FakeApertureScatterguard = make_fake_device(ApertureScatterguard)
    ap_sg: ApertureScatterguard = FakeApertureScatterguard(name="test_ap_sg")
    with (
        patch_motor(ap_sg.aperture.x),
        patch_motor(ap_sg.aperture.y),
        patch_motor(ap_sg.aperture.z),
        patch_motor(ap_sg.scatterguard.x),
        patch_motor(ap_sg.scatterguard.y),
    ):
        yield ap_sg


@pytest.fixture
def aperture_in_medium_pos(
    ap_sg: ApertureScatterguard,
    aperture_positions: AperturePositions,
):
    ap_sg.load_aperture_positions(aperture_positions)

    medium = aperture_positions.MEDIUM.location
    ap_sg.aperture.x.set(medium.aperture_x)
    ap_sg.aperture.y.set(medium.aperture_y)
    ap_sg.aperture.z.set(medium.aperture_z)
    ap_sg.scatterguard.x.set(medium.scatterguard_x)
    ap_sg.scatterguard.y.set(medium.scatterguard_y)
    yield ap_sg


@pytest.fixture
def aperture_positions():
    aperture_positions = AperturePositions.from_gda_beamline_params(
        {
            "miniap_x_LARGE_APERTURE": 2.389,
            "miniap_y_LARGE_APERTURE": 40.986,
            "miniap_z_LARGE_APERTURE": 15.8,
            "sg_x_LARGE_APERTURE": 5.25,
            "sg_y_LARGE_APERTURE": 4.43,
            "miniap_x_MEDIUM_APERTURE": 2.384,
            "miniap_y_MEDIUM_APERTURE": 44.967,
            "miniap_z_MEDIUM_APERTURE": 15.8,
            "sg_x_MEDIUM_APERTURE": 5.285,
            "sg_y_MEDIUM_APERTURE": 0.46,
            "miniap_x_SMALL_APERTURE": 2.430,
            "miniap_y_SMALL_APERTURE": 48.974,
            "miniap_z_SMALL_APERTURE": 15.8,
            "sg_x_SMALL_APERTURE": 5.3375,
            "sg_y_SMALL_APERTURE": -3.55,
            "miniap_x_ROBOT_LOAD": 2.386,
            "miniap_y_ROBOT_LOAD": 31.40,
            "miniap_z_ROBOT_LOAD": 15.8,
            "sg_x_ROBOT_LOAD": 5.25,
            "sg_y_ROBOT_LOAD": 4.43,
        }
    )
    return aperture_positions


def test_aperture_scatterguard_rejects_unknown_position(aperture_in_medium_pos):
    position_to_reject = ApertureFiveDimensionalLocation(0, 0, 0, 0, 0)

    with pytest.raises(InvalidApertureMove):
        aperture_in_medium_pos.set(
            SingleAperturePosition("test", 10, position_to_reject)
        )


def test_aperture_scatterguard_select_bottom_moves_sg_down_then_assembly_up(
    aperture_positions: AperturePositions,
    aperture_in_medium_pos: ApertureScatterguard,
):
    aperture_scatterguard = aperture_in_medium_pos
    call_logger = install_logger_for_aperture_and_scatterguard(aperture_scatterguard)

    aperture_scatterguard.set(aperture_positions.SMALL)

    actual_calls = call_logger.mock_calls
    expected_calls = [
        ("_mock_sg_x", (5.3375,)),
        ("_mock_sg_y", (-3.55,)),
        lambda call: call[0].endswith("__and__().wait"),
        ("_mock_ap_x", (2.43,)),
        ("_mock_ap_y", (48.974,)),
        ("_mock_ap_z", (15.8,)),
    ]

    compare_actual_and_expected_calls(actual_calls, expected_calls)


def test_aperture_scatterguard_select_top_moves_assembly_down_then_sg_up(
    aperture_positions: AperturePositions, aperture_in_medium_pos: ApertureScatterguard
):
    aperture_scatterguard = aperture_in_medium_pos
    call_logger = install_logger_for_aperture_and_scatterguard(aperture_scatterguard)

    aperture_scatterguard.set(aperture_positions.LARGE)

    actual_calls = call_logger.mock_calls
    expected_calls = [
        ("_mock_ap_x", (2.389,)),
        ("_mock_ap_y", (40.986,)),
        ("_mock_ap_z", (15.8,)),
        lambda call: call[0].endswith("__and__().wait"),
        ("_mock_sg_x", (5.25,)),
        ("_mock_sg_y", (4.43,)),
    ]

    compare_actual_and_expected_calls(actual_calls, expected_calls)


def test_aperture_scatterguard_throws_error_if_outside_tolerance(
    ap_sg: ApertureScatterguard,
):
    ap_sg.aperture.z.motor_resolution.sim_put(0.001)  # type: ignore
    ap_sg.aperture.z.user_setpoint.sim_put(1)  # type: ignore
    ap_sg.aperture.z.motor_done_move.sim_put(1)  # type: ignore

    with pytest.raises(InvalidApertureMove):
        pos = ApertureFiveDimensionalLocation(0, 0, 1.1, 0, 0)
        ap_sg._safe_move_within_datacollection_range(pos)


def test_aperture_scatterguard_returns_status_if_within_tolerance(
    ap_sg: ApertureScatterguard,
):
    ap_sg.aperture.z.motor_resolution.sim_put(0.001)  # type: ignore
    ap_sg.aperture.z.user_setpoint.sim_put(1)  # type: ignore
    ap_sg.aperture.z.motor_done_move.sim_put(1)  # type: ignore

    pos = ApertureFiveDimensionalLocation(0, 0, 1, 0, 0)
    status = ap_sg._safe_move_within_datacollection_range(pos)
    assert isinstance(status, StatusBase)


def test_aperture_positions_get_new_position_truthy_exact(aperture_positions):
    should_be_large = ApertureFiveDimensionalLocation(2.389, 40.986, 15.8, 5.25, 4.43)
    new_position = aperture_positions.get_new_position(should_be_large)
    assert new_position == aperture_positions.LARGE


def test_aperture_positions_get_new_position_truthy_inside_tolerance(
    aperture_positions,
):
    should_be_large = ApertureFiveDimensionalLocation(2.389, 40.9865, 15.8, 5.25, 4.43)
    new_position = aperture_positions.get_new_position(should_be_large)
    assert new_position == aperture_positions.LARGE


def test_aperture_positions_get_new_position_falsy(aperture_positions):
    large_missed_by_2_at_y = ApertureFiveDimensionalLocation(
        2.389, 42, 15.8, 5.25, 4.43
    )
    with pytest.raises(InvalidApertureMove):
        aperture_positions.get_new_position(large_missed_by_2_at_y)


def test_aperture_positions_get_new_position_robot_load_exact(aperture_positions):
    robot_exact = ApertureFiveDimensionalLocation(
        2.386,
        31.40,
        15.8,
        5.25,
        4.43,
    )
    new_position = aperture_positions.get_new_position(robot_exact)
    assert new_position is aperture_positions.ROBOT_LOAD


def test_given_aperture_not_set_through_device_but_motors_in_position_when_device_read_then_position_returned(
    aperture_in_medium_pos: ApertureScatterguard, aperture_positions: AperturePositions
):
    selected_aperture = aperture_in_medium_pos.read()
    assert (
        selected_aperture["test_ap_sg_selected_aperture"]["value"]
        == aperture_positions.MEDIUM
    )


def test_when_aperture_set_and_device_read_then_position_returned(
    aperture_in_medium_pos: ApertureScatterguard, aperture_positions: AperturePositions
):
    set_status = aperture_in_medium_pos.set(aperture_positions.SMALL)
    set_status.wait()
    selected_aperture = aperture_in_medium_pos.read()
    assert (
        selected_aperture["test_ap_sg_selected_aperture"]["value"]
        == aperture_positions.SMALL
    )


def install_logger_for_aperture_and_scatterguard(aperture_scatterguard):
    parent_mock = MagicMock()
    mock_ap_x = MagicMock(aperture_scatterguard.aperture.x.set)
    mock_ap_y = MagicMock(aperture_scatterguard.aperture.y.set)
    mock_ap_z = MagicMock(aperture_scatterguard.aperture.z.set)
    mock_sg_x = MagicMock(aperture_scatterguard.scatterguard.x.set)
    mock_sg_y = MagicMock(aperture_scatterguard.scatterguard.y.set)
    aperture_scatterguard.aperture.x.set = mock_ap_x
    aperture_scatterguard.aperture.y.set = mock_ap_y
    aperture_scatterguard.aperture.z.set = mock_ap_z
    aperture_scatterguard.scatterguard.x.set = mock_sg_x
    aperture_scatterguard.scatterguard.y.set = mock_sg_y
    parent_mock.attach_mock(mock_ap_x, "_mock_ap_x")
    parent_mock.attach_mock(mock_ap_y, "_mock_ap_y")
    parent_mock.attach_mock(mock_ap_z, "_mock_ap_z")
    parent_mock.attach_mock(mock_sg_x, "_mock_sg_x")
    parent_mock.attach_mock(mock_sg_y, "_mock_sg_y")
    return parent_mock


def compare_actual_and_expected_calls(actual_calls, expected_calls):
    # ideally, we could use MagicMock.assert_has_calls but a) it doesn't work properly and b) doesn't do what I need
    i_actual = 0
    for i, expected in enumerate(expected_calls):
        if isinstance(expected, tuple):
            # simple comparison
            i_actual = actual_calls.index(expected, i_actual)
        else:
            # expected is a predicate to be satisfied
            i_matches = [
                i for i, call in enumerate(actual_calls[i_actual:]) if expected(call)
            ]
            if i_matches:
                i_actual = i_matches[0]
            else:
                raise ValueError("Couldn't find call matching predicate")

        i_actual += 1
