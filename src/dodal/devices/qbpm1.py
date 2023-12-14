from ophyd import Component as Cpt
from ophyd import Device, EpicsSignalRO, Kind


class QBPM1(Device):
    intensity = Cpt(EpicsSignalRO, "-DI-QBPM-01:INTEN", kind=Kind.normal)
