from enum import Enum


class DateType(str, Enum):
    YEAR = "year"
    HALF_YEAR = "half_year"
    QUARTER = "quarter"
    MONTH = "month"
    DAY = "day"


class ValueType(str, Enum):
    REAL = "real"
    TARGET = "target"
    FORECAST = "forecast"


class Ordering(str, Enum):
    ASC = "asc"
    DESC = "desc"


class NormativeType(Enum):
    SELF = "self"
    PARENT = "parent"
    GLOBAL = "global"


class InfrastructureType(Enum):
    BASIC = "basic"
    ADDITIONAL = "additional"
    COMFORT = "comfort"


class RoadType(Enum):
    FEDERAL = "federal"
    REGIONAL = "regional"
    LOCAL = "local"
