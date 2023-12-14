from ophyd import Component as Cpt
from ophyd import Device, EpicsSignalRO, Kind


class IPin(Device):
    """Simple device to get the ipin reading"""

    reading = Cpt(EpicsSignalRO, "I", kind=Kind.hinted)
