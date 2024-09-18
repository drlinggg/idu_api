from geoalchemy2.functions import ST_AsGeoJSON
from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from idu_api.common.db.entities import (
    object_geometries_data,
    physical_object_types_dict,
    physical_objects_data,
    service_types_dict,
    services_data,
    territory_types_dict,
    urban_objects_data,
)
from idu_api.urban_api.dto import ScenarioUrbanObjectDTO
from idu_api.urban_api.exceptions.logic.common import EntityNotFoundById


async def get_scenario_urban_object_by_id_from_db(
    conn: AsyncConnection, scenario_urban_object_id: int
) -> ScenarioUrbanObjectDTO:
    """Get urban object by urban object id."""

    statement = (
        select(
            urban_objects_data,
            physical_objects_data.c.physical_object_type_id,
            urban_objects_data.c.scenario_id,
            physical_object_types_dict.c.name.label("physical_object_type_name"),
            physical_objects_data.c.name.label("physical_object_name"),
            physical_objects_data.c.properties.label("physical_object_properties"),
            physical_objects_data.c.created_at.label("physical_object_created_at"),
            physical_objects_data.c.updated_at.label("physical_object_updated_at"),
            object_geometries_data.c.territory_id,
            cast(ST_AsGeoJSON(object_geometries_data.c.geometry), JSONB).label("geometry"),
            cast(ST_AsGeoJSON(object_geometries_data.c.centre_point), JSONB).label("centre_point"),
            services_data.c.name.label("service_name"),
            services_data.c.capacity_real,
            services_data.c.properties.label("service_properties"),
            services_data.c.created_at.label("service_created_at"),
            services_data.c.updated_at.label("service_updated_at"),
            object_geometries_data.c.address,
            service_types_dict.c.service_type_id,
            service_types_dict.c.urban_function_id,
            service_types_dict.c.name.label("service_type_name"),
            service_types_dict.c.capacity_modeled.label("service_type_capacity_modeled"),
            service_types_dict.c.code.label("service_type_code"),
            territory_types_dict.c.territory_type_id,
            territory_types_dict.c.name.label("territory_type_name"),
        )
        .select_from(
            urban_objects_data.join(
                physical_objects_data,
                physical_objects_data.c.physical_object_id == urban_objects_data.c.physical_object_id,
            )
            .join(
                object_geometries_data,
                object_geometries_data.c.object_geometry_id == urban_objects_data.c.object_geometry_id,
            )
            .join(
                physical_object_types_dict,
                physical_object_types_dict.c.physical_object_type_id == physical_objects_data.c.physical_object_type_id,
            )
            .outerjoin(services_data, services_data.c.service_id == urban_objects_data.c.service_id)
            .outerjoin(service_types_dict, service_types_dict.c.service_type_id == services_data.c.service_type_id)
            .outerjoin(
                territory_types_dict, territory_types_dict.c.territory_type_id == services_data.c.territory_type_id
            )
        )
        .where(urban_objects_data.c.urban_object_id == scenario_urban_object_id)
    )

    scenario_urban_object = (await conn.execute(statement)).mappings().one_or_none()
    if scenario_urban_object is None:
        raise EntityNotFoundById(scenario_urban_object_id, "scenario urban object")

    return ScenarioUrbanObjectDTO(**scenario_urban_object)
