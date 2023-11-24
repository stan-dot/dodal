from typing import Any

import numpy as np
import pytest

from dodal.devices.zocalo_results_device import XrcResult, ZocaloResults, parse_reading

TEST_RESULTS: list[XrcResult] = [
    {
        "centre_of_mass": [1, 2, 3],
        "max_voxel": [2, 4, 5],
        "max_count": 105062,
        "n_voxels": 38,
        "total_count": 2387574,
        "bounding_box": [[1, 2, 3], [3, 4, 4]],
    },
    {
        "centre_of_mass": [2, 3, 4],
        "max_voxel": [2, 4, 5],
        "max_count": 105123,
        "n_voxels": 35,
        "total_count": 2387574,
        "bounding_box": [[1, 2, 3], [3, 4, 4]],
    },
    {
        "centre_of_mass": [4, 5, 6],
        "max_voxel": [2, 4, 5],
        "max_count": 102062,
        "n_voxels": 31,
        "total_count": 2387574,
        "bounding_box": [[1, 2, 3], [3, 4, 4]],
    },
]

TEST_READING = {
    "zocalo_results-centre_of_mass": {
        "value": np.array([2, 3, 4]),
        "timestamp": 11250827.378482452,
        "alarm_severity": 0,
    },
    "zocalo_results-max_voxel": {
        "value": np.array([2, 4, 5]),
        "timestamp": 11250827.378502235,
        "alarm_severity": 0,
    },
    "zocalo_results-max_count": {
        "value": 105123,
        "timestamp": 11250827.378515247,
        "alarm_severity": 0,
    },
    "zocalo_results-n_voxels": {
        "value": 35,
        "timestamp": 11250827.37852733,
        "alarm_severity": 0,
    },
    "zocalo_results-total_count": {
        "value": 2387574,
        "timestamp": 11250827.378539408,
        "alarm_severity": 0,
    },
    "zocalo_results-bounding_box": {
        "value": np.array([[1, 2, 3], [3, 4, 4]]),
        "timestamp": 11250827.378558964,
        "alarm_severity": 0,
    },
}


def assert_reading_equals_xrcresult(read_result: dict[str, Any], expected: XrcResult):
    parsed_reading = parse_reading(read_result)

    assert parsed_reading["centre_of_mass"] == expected["centre_of_mass"]
    assert parsed_reading["max_voxel"] == expected["max_voxel"]
    assert parsed_reading["max_count"] == expected["max_count"]
    assert parsed_reading["n_voxels"] == expected["n_voxels"]
    assert parsed_reading["total_count"] == expected["total_count"]
    assert parsed_reading["bounding_box"] == expected["bounding_box"]


def test_parse_reading():
    assert_reading_equals_xrcresult(TEST_READING, TEST_RESULTS[1])


@pytest.mark.asyncio
async def test_put_result():
    zocalo_device = ZocaloResults()
    await zocalo_device.connect()
    await zocalo_device._put_result(TEST_RESULTS[0])
    result = await zocalo_device.read()
    assert_reading_equals_xrcresult(result, TEST_RESULTS[0])
