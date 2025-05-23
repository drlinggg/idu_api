"""Enumerations converted to database datatypes are defined here."""

from enum import Enum


# pylint: disable=invalid-name
class DateFieldType(str, Enum):
    """
    Enumeration of date field types.
    """

    year = "year"
    half_year = "half_year"
    quarter = "quarter"
    month = "month"
    day = "day"


# pylint: disable=invalid-name
class IndicatorValueType(str, Enum):
    """
    Enumeration of indicator value types.
    """

    real = "real"
    forecast = "forecast"
    target = "target"


class InfrastructureType(str, Enum):
    """
    Enumeration of infrastructure types.
    """

    basic = "basic"
    additional = "additional"
    comfort = "comfort"


class ScenarioPhase(str, Enum):
    """
    Enumeration of scenario phases.
    """

    investment = "investment"
    pre_design = "pre_design"
    design = "design"
    construction = "construction"
    operation = "operation"
    decommission = "decommission"
