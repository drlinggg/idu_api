"""Object geometries DTOs are defined here."""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import shapely.geometry as geom

from idu_api.urban_api.dto.physical_objects import ShortScenarioPhysicalObjectDTO, ShortPhysicalObjectDTO
from idu_api.urban_api.dto.services import ShortScenarioServiceDTO, ShortServiceDTO

Geom = geom.Polygon | geom.MultiPolygon | geom.Point | geom.LineString | geom.MultiLineString


@dataclass
class ObjectGeometryDTO:
    object_geometry_id: int
    territory_id: int
    territory_name: str
    address: str | None
    osm_id: str | None
    geometry: Geom
    centre_point: geom.Point
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.centre_point, dict):
            self.centre_point = geom.shape(self.centre_point)
        if self.geometry is None:
            self.geometry = self.centre_point
        if isinstance(self.geometry, dict):
            self.geometry = geom.shape(self.geometry)


@dataclass
class ScenarioGeometryDTO(ObjectGeometryDTO):
    is_scenario_object: bool

    def __post_init__(self) -> None:
        if isinstance(self.centre_point, dict):
            self.centre_point = geom.shape(self.centre_point)
        if self.geometry is None:
            self.geometry = self.centre_point
        if isinstance(self.geometry, dict):
            self.geometry = geom.shape(self.geometry)

    def to_geojson_dict(self) -> dict[str, Any]:
        geometry = asdict(self)
        territory = {
            "id": geometry.pop("territory_id"),
            "name": geometry.pop("territory_name"),
        }
        geometry["territory"] = territory
        return geometry


@dataclass
class GeometryWithAllObjectsDTO:
    object_geometry_id: int
    territory_id: int
    address: str | None
    osm_id: str | None
    geometry: Geom
    centre_point: geom.Point
    physical_objects: list[ShortPhysicalObjectDTO]
    services: list[ShortServiceDTO]

    def __post_init__(self) -> None:
        if isinstance(self.centre_point, dict):
            self.centre_point = geom.shape(self.centre_point)
        if self.geometry is None:
            self.geometry = self.centre_point
        if isinstance(self.geometry, dict):
            self.geometry = geom.shape(self.geometry)

    def to_geojson_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioGeometryWithAllObjectsDTO:
    object_geometry_id: int
    territory_id: int
    address: str | None
    osm_id: str | None
    geometry: Geom
    centre_point: geom.Point
    is_scenario_object: bool
    physical_objects: list[ShortScenarioPhysicalObjectDTO]
    services: list[ShortScenarioServiceDTO]

    def __post_init__(self) -> None:
        if isinstance(self.centre_point, dict):
            self.centre_point = geom.shape(self.centre_point)
        if self.geometry is None:
            self.geometry = self.centre_point
        if isinstance(self.geometry, dict):
            self.geometry = geom.shape(self.geometry)

    def to_geojson_dict(self) -> dict[str, Any]:
        return asdict(self)
