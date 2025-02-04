"""Projects geometries internal logic is defined here."""

from collections import defaultdict
from datetime import datetime, timezone

from geoalchemy2.functions import (
    ST_AsGeoJSON,
    ST_Centroid,
    ST_GeomFromText,
    ST_Intersection,
    ST_Intersects,
    ST_Union,
    ST_Within,
)
from sqlalchemy import cast, delete, insert, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from idu_api.common.db.entities import (
    living_buildings_data,
    object_geometries_data,
    physical_object_functions_dict,
    physical_object_types_dict,
    physical_objects_data,
    projects_data,
    projects_living_buildings_data,
    projects_object_geometries_data,
    projects_physical_objects_data,
    projects_services_data,
    projects_territory_data,
    projects_urban_objects_data,
    scenarios_data,
    service_types_dict,
    services_data,
    territories_data,
    territory_types_dict,
    urban_functions_dict,
    urban_objects_data,
)
from idu_api.urban_api.dto import (
    ObjectGeometryDTO,
    ScenarioGeometryDTO,
    ScenarioGeometryWithAllObjectsDTO,
)
from idu_api.urban_api.dto.object_geometries import GeometryWithAllObjectsDTO
from idu_api.urban_api.exceptions.logic.common import EntityAlreadyExists, EntityNotFoundById, EntityNotFoundByParams
from idu_api.urban_api.exceptions.logic.users import AccessDeniedError
from idu_api.urban_api.schemas import ObjectGeometriesPatch, ObjectGeometriesPut


async def get_geometries_by_scenario_id_from_db(
    conn: AsyncConnection,
    scenario_id: int,
    user_id: str,
    physical_object_id: int | None,
    service_id: int | None,
) -> list[ScenarioGeometryDTO]:
    """Get geometries by scenario identifier."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id and not project.public:
        raise AccessDeniedError(project_id, "project")

    project_geometry = (
        select(projects_territory_data.c.geometry).where(projects_territory_data.c.project_id == project.project_id)
    ).alias("project_geometry")

    # Шаг 1: Получить все public_urban_object_id для данного scenario_id
    public_urban_object_ids = (
        select(projects_urban_objects_data.c.public_urban_object_id)
        .where(projects_urban_objects_data.c.scenario_id == scenario_id)
        .where(projects_urban_objects_data.c.public_urban_object_id.isnot(None))
    ).alias("public_urban_object_ids")

    # Шаг 2: Собрать все записи из public.urban_objects_data по собранным public_urban_object_id
    public_urban_objects_query = (
        select(
            object_geometries_data.c.object_geometry_id,
            object_geometries_data.c.territory_id,
            territories_data.c.name.label("territory_name"),
            object_geometries_data.c.address,
            object_geometries_data.c.osm_id,
            cast(ST_AsGeoJSON(object_geometries_data.c.geometry), JSONB).label("geometry"),
            cast(ST_AsGeoJSON(object_geometries_data.c.centre_point), JSONB).label("centre_point"),
            object_geometries_data.c.created_at,
            object_geometries_data.c.updated_at,
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
                territories_data,
                territories_data.c.territory_id == object_geometries_data.c.territory_id,
            )
            .outerjoin(services_data, services_data.c.service_id == urban_objects_data.c.service_id)
        )
        .where(
            urban_objects_data.c.urban_object_id.not_in(select(public_urban_object_ids)),
            ST_Within(object_geometries_data.c.geometry, select(project_geometry).scalar_subquery()),
        )
        .distinct()
    )

    # Условия фильтрации для public объектов
    if physical_object_id is not None:
        public_urban_objects_query = public_urban_objects_query.where(
            physical_objects_data.c.physical_object_id == physical_object_id
        )
    if service_id is not None:
        public_urban_objects_query = public_urban_objects_query.where(services_data.c.service_id == service_id)

    # Получаем все объекты из public.urban_objects_data
    public_objects = []
    for row in (await conn.execute(public_urban_objects_query)).mappings().all():
        public_objects.append(
            {
                "object_geometry_id": row.object_geometry_id,
                "territory_id": row.territory_id,
                "territory_name": row.territory_name,
                "geometry": row.geometry,
                "centre_point": row.centre_point,
                "address": row.address,
                "osm_id": row.osm_id,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "is_scenario_object": False,
            }
        )

    # Шаг 3: Собрать все записи из user_projects.urban_objects_data для данного сценария
    scenario_urban_objects_query = (
        select(
            projects_urban_objects_data.c.object_geometry_id,
            territories_data.c.territory_id,
            territories_data.c.name.label("territory_name"),
            projects_object_geometries_data.c.address,
            projects_object_geometries_data.c.osm_id,
            cast(ST_AsGeoJSON(projects_object_geometries_data.c.geometry), JSONB).label("geometry"),
            cast(ST_AsGeoJSON(projects_object_geometries_data.c.centre_point), JSONB).label("centre_point"),
            projects_object_geometries_data.c.created_at,
            projects_object_geometries_data.c.updated_at,
            object_geometries_data.c.object_geometry_id.label("public_object_geometry_id"),
            object_geometries_data.c.address.label("public_address"),
            object_geometries_data.c.osm_id.label("public_osm_id"),
            cast(ST_AsGeoJSON(object_geometries_data.c.geometry), JSONB).label("public_geometry"),
            cast(ST_AsGeoJSON(object_geometries_data.c.centre_point), JSONB).label("public_centre_point"),
            object_geometries_data.c.created_at.label("public_created_at"),
            object_geometries_data.c.updated_at.label("public_updated_at"),
        )
        .select_from(
            projects_urban_objects_data.outerjoin(
                projects_physical_objects_data,
                projects_physical_objects_data.c.physical_object_id == projects_urban_objects_data.c.physical_object_id,
            )
            .outerjoin(
                projects_object_geometries_data,
                projects_object_geometries_data.c.object_geometry_id
                == projects_urban_objects_data.c.object_geometry_id,
            )
            .outerjoin(
                projects_services_data, projects_services_data.c.service_id == projects_urban_objects_data.c.service_id
            )
            .outerjoin(
                physical_objects_data,
                physical_objects_data.c.physical_object_id == projects_urban_objects_data.c.public_physical_object_id,
            )
            .outerjoin(
                object_geometries_data,
                object_geometries_data.c.object_geometry_id == projects_urban_objects_data.c.public_object_geometry_id,
            )
            .outerjoin(services_data, services_data.c.service_id == projects_urban_objects_data.c.public_service_id)
            .outerjoin(
                territories_data,
                or_(
                    territories_data.c.territory_id == object_geometries_data.c.territory_id,
                    territories_data.c.territory_id == projects_object_geometries_data.c.territory_id,
                ),
            )
        )
        .where(projects_urban_objects_data.c.scenario_id == scenario_id)
        .where(projects_urban_objects_data.c.public_urban_object_id.is_(None))
        .distinct()
    )

    # Условия фильтрации для объектов user_projects
    if physical_object_id is not None:
        scenario_urban_objects_query = scenario_urban_objects_query.where(
            physical_objects_data.c.physical_object_id == physical_object_id
        )
    if service_id is not None:
        scenario_urban_objects_query = scenario_urban_objects_query.where(services_data.c.service_id == service_id)

    # Получаем все объекты из user_projects.urban_objects_data
    scenario_objects = []
    for row in (await conn.execute(scenario_urban_objects_query)).mappings().all():
        is_scenario_geometry = row.object_geometry_id is not None and row.public_object_geometry_id is None
        scenario_objects.append(
            {
                "object_geometry_id": row.object_geometry_id or row.public_object_geometry_id,
                "territory_id": row.territory_id,
                "territory_name": row.territory_name,
                "geometry": row.geometry if is_scenario_geometry else row.public_geometry,
                "centre_point": row.centre_point if is_scenario_geometry else row.public_centre_point,
                "address": row.address if is_scenario_geometry else row.public_address,
                "osm_id": row.osm_id if is_scenario_geometry else row.public_osm_id,
                "created_at": row.created_at if is_scenario_geometry else row.public_created_at,
                "updated_at": row.updated_at if is_scenario_geometry else row.public_updated_at,
                "is_scenario_object": is_scenario_geometry,
            }
        )

    grouped_objects = defaultdict()
    for obj in public_objects + scenario_objects:
        geometry_id = obj["object_geometry_id"]
        is_scenario_geometry = obj["is_scenario_object"]

        # Проверка и добавление геометрии
        existing_entry = grouped_objects.get(geometry_id)
        if existing_entry is None:
            grouped_objects[geometry_id] = {
                "object_geometry_id": geometry_id,
                "territory_id": obj.get("territory_id"),
                "territory_name": obj.get("territory_name"),
                "geometry": obj.get("geometry"),
                "centre_point": obj.get("centre_point"),
                "address": obj.get("address"),
                "osm_id": obj.get("osm_id"),
                "created_at": obj.get("created_at"),
                "updated_at": obj.get("updated_at"),
                "is_scenario_object": is_scenario_geometry,
            }
        elif existing_entry.get("is_scenario_object") != is_scenario_geometry:
            grouped_objects[-geometry_id] = {
                "object_geometry_id": geometry_id,
                "territory_id": obj.get("territory_id"),
                "territory_name": obj.get("territory_name"),
                "geometry": obj.get("geometry"),
                "centre_point": obj.get("centre_point"),
                "address": obj.get("address"),
                "osm_id": obj.get("osm_id"),
                "created_at": obj.get("created_at"),
                "updated_at": obj.get("updated_at"),
                "is_scenario_object": is_scenario_geometry,
            }

    return [ScenarioGeometryDTO(**row) for row in list(grouped_objects.values())]


async def get_geometries_with_all_objects_by_scenario_id_from_db(
    conn: AsyncConnection,
    scenario_id: int,
    user_id: str,
    physical_object_type_id: int | None,
    service_type_id: int | None,
    physical_object_function_id: int | None,
    urban_function_id: int | None,
) -> list[ScenarioGeometryWithAllObjectsDTO]:
    """Get geometries with list of physical objects and services by scenario identifier."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id and not project.public:
        raise AccessDeniedError(project_id, "project")

    project_geometry = (
        select(projects_territory_data.c.geometry).where(projects_territory_data.c.project_id == project.project_id)
    ).alias("project_geometry")

    # Шаг 1: Получить все public_urban_object_id для данного scenario_id
    public_urban_object_ids = (
        select(projects_urban_objects_data.c.public_urban_object_id)
        .where(projects_urban_objects_data.c.scenario_id == scenario_id)
        .where(projects_urban_objects_data.c.public_urban_object_id.isnot(None))
    ).alias("public_urban_object_ids")

    # Шаг 2: Собрать все записи из public.urban_objects_data по собранным public_urban_object_id
    public_urban_objects_query = (
        select(
            physical_objects_data.c.physical_object_id,
            physical_object_types_dict.c.physical_object_type_id,
            physical_object_types_dict.c.name.label("physical_object_type_name"),
            physical_objects_data.c.name.label("physical_object_name"),
            physical_objects_data.c.properties.label("physical_object_properties"),
            living_buildings_data.c.living_building_id,
            living_buildings_data.c.living_area,
            living_buildings_data.c.properties.label("living_building_properties"),
            object_geometries_data.c.object_geometry_id,
            territories_data.c.territory_id,
            territories_data.c.name.label("territory_name"),
            object_geometries_data.c.address,
            object_geometries_data.c.osm_id,
            cast(ST_AsGeoJSON(object_geometries_data.c.geometry), JSONB).label("geometry"),
            cast(ST_AsGeoJSON(object_geometries_data.c.centre_point), JSONB).label("centre_point"),
            services_data.c.service_id,
            services_data.c.name.label("service_name"),
            services_data.c.capacity_real,
            services_data.c.properties.label("service_properties"),
            service_types_dict.c.service_type_id,
            service_types_dict.c.name.label("service_type_name"),
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
            .outerjoin(services_data, services_data.c.service_id == urban_objects_data.c.service_id)
            .join(
                physical_object_types_dict,
                physical_object_types_dict.c.physical_object_type_id == physical_objects_data.c.physical_object_type_id,
            )
            .outerjoin(
                service_types_dict,
                service_types_dict.c.service_type_id == services_data.c.service_type_id,
            )
            .outerjoin(
                territory_types_dict,
                territory_types_dict.c.territory_type_id == services_data.c.territory_type_id,
            )
            .outerjoin(
                living_buildings_data,
                living_buildings_data.c.physical_object_id == physical_objects_data.c.physical_object_id,
            )
            .join(
                territories_data,
                territories_data.c.territory_id == object_geometries_data.c.territory_id,
            )
        )
        .where(
            urban_objects_data.c.urban_object_id.not_in(select(public_urban_object_ids)),
            ST_Within(object_geometries_data.c.geometry, select(project_geometry).scalar_subquery()),
        )
    )

    # Шаг 3: Собрать все записи из user_projects.urban_objects_data для данного сценария
    scenario_urban_objects_query = (
        select(
            projects_urban_objects_data.c.urban_object_id,
            projects_urban_objects_data.c.physical_object_id,
            projects_urban_objects_data.c.object_geometry_id,
            projects_urban_objects_data.c.service_id,
            projects_urban_objects_data.c.public_physical_object_id,
            projects_urban_objects_data.c.public_object_geometry_id,
            projects_urban_objects_data.c.public_service_id,
            projects_physical_objects_data.c.name.label("physical_object_name"),
            projects_physical_objects_data.c.properties.label("physical_object_properties"),
            projects_living_buildings_data.c.living_building_id,
            projects_living_buildings_data.c.living_area,
            projects_living_buildings_data.c.properties.label("living_building_properties"),
            projects_object_geometries_data.c.territory_id,
            projects_object_geometries_data.c.address,
            projects_object_geometries_data.c.osm_id,
            cast(ST_AsGeoJSON(projects_object_geometries_data.c.geometry), JSONB).label("geometry"),
            cast(ST_AsGeoJSON(projects_object_geometries_data.c.centre_point), JSONB).label("centre_point"),
            projects_services_data.c.name.label("service_name"),
            projects_services_data.c.capacity_real,
            projects_services_data.c.properties.label("service_properties"),
            physical_objects_data.c.name.label("public_physical_object_name"),
            physical_objects_data.c.properties.label("public_physical_object_properties"),
            living_buildings_data.c.living_building_id.label("public_living_building_id"),
            living_buildings_data.c.living_area.label("public_living_area"),
            living_buildings_data.c.properties.label("public_living_building_properties"),
            object_geometries_data.c.address.label("public_address"),
            object_geometries_data.c.osm_id.label("public_osm_id"),
            cast(ST_AsGeoJSON(object_geometries_data.c.geometry), JSONB).label("public_geometry"),
            cast(ST_AsGeoJSON(object_geometries_data.c.centre_point), JSONB).label("public_centre_point"),
            services_data.c.name.label("public_service_name"),
            services_data.c.capacity_real.label("public_capacity_real"),
            services_data.c.properties.label("public_service_properties"),
            physical_object_types_dict.c.physical_object_type_id,
            physical_object_types_dict.c.name.label("physical_object_type_name"),
            territories_data.c.territory_id,
            territories_data.c.name.label("territory_name"),
            service_types_dict.c.service_type_id,
            service_types_dict.c.name.label("service_type_name"),
            territory_types_dict.c.territory_type_id,
            territory_types_dict.c.name.label("territory_type_name"),
        )
        .select_from(
            projects_urban_objects_data.outerjoin(
                projects_physical_objects_data,
                projects_physical_objects_data.c.physical_object_id == projects_urban_objects_data.c.physical_object_id,
            )
            .outerjoin(
                projects_object_geometries_data,
                projects_object_geometries_data.c.object_geometry_id
                == projects_urban_objects_data.c.object_geometry_id,
            )
            .outerjoin(
                projects_services_data, projects_services_data.c.service_id == projects_urban_objects_data.c.service_id
            )
            .outerjoin(
                physical_objects_data,
                physical_objects_data.c.physical_object_id == projects_urban_objects_data.c.public_physical_object_id,
            )
            .outerjoin(
                object_geometries_data,
                object_geometries_data.c.object_geometry_id == projects_urban_objects_data.c.public_object_geometry_id,
            )
            .outerjoin(services_data, services_data.c.service_id == projects_urban_objects_data.c.public_service_id)
            .outerjoin(
                physical_object_types_dict,
                or_(
                    physical_object_types_dict.c.physical_object_type_id
                    == projects_physical_objects_data.c.physical_object_type_id,
                    physical_object_types_dict.c.physical_object_type_id
                    == physical_objects_data.c.physical_object_type_id,
                ),
            )
            .outerjoin(
                service_types_dict,
                or_(
                    service_types_dict.c.service_type_id == projects_services_data.c.service_type_id,
                    service_types_dict.c.service_type_id == services_data.c.service_type_id,
                ),
            )
            .outerjoin(
                territory_types_dict,
                or_(
                    territory_types_dict.c.territory_type_id == projects_services_data.c.territory_type_id,
                    territory_types_dict.c.territory_type_id == services_data.c.territory_type_id,
                ),
            )
            .outerjoin(
                territories_data,
                or_(
                    territories_data.c.territory_id == projects_object_geometries_data.c.territory_id,
                    territories_data.c.territory_id == object_geometries_data.c.territory_id,
                ),
            )
            .outerjoin(
                living_buildings_data,
                living_buildings_data.c.physical_object_id == physical_objects_data.c.physical_object_id,
            )
            .outerjoin(
                projects_living_buildings_data,
                projects_living_buildings_data.c.physical_object_id
                == projects_physical_objects_data.c.physical_object_id,
            )
        )
        .where(
            projects_urban_objects_data.c.scenario_id == scenario_id,
            projects_urban_objects_data.c.public_urban_object_id.is_(None),
        )
    )

    # Условия фильтрации для объектов
    if physical_object_type_id is not None and physical_object_function_id is not None:
        raise EntityNotFoundByParams(
            "physical object type and function", physical_object_type_id, physical_object_function_id
        )
    if physical_object_type_id is not None:
        public_urban_objects_query = public_urban_objects_query.where(
            projects_physical_objects_data.c.physical_object_type_id == physical_object_type_id
        )
        scenario_urban_objects_query = scenario_urban_objects_query.where(
            (projects_physical_objects_data.c.physical_object_type_id == physical_object_type_id)
            | (physical_objects_data.c.physical_object_type_id == physical_object_type_id)
        )
    elif physical_object_function_id is not None:
        physical_object_functions_cte = (
            select(
                physical_object_functions_dict.c.physical_object_function_id,
                physical_object_functions_dict.c.parent_id,
            )
            .where(physical_object_functions_dict.c.physical_object_function_id == physical_object_function_id)
            .cte(recursive=True)
        )
        physical_object_functions_cte = physical_object_functions_cte.union_all(
            select(
                physical_object_functions_dict.c.physical_object_function_id,
                physical_object_functions_dict.c.parent_id,
            ).join(
                physical_object_functions_cte,
                physical_object_functions_dict.c.parent_id
                == physical_object_functions_cte.c.physical_object_function_id,
            )
        )
        public_urban_objects_query = public_urban_objects_query.where(
            physical_object_types_dict.c.physical_object_function_id.in_(
                select(physical_object_functions_cte.c.physical_object_function_id)
            )
        )
        scenario_urban_objects_query = scenario_urban_objects_query.where(
            physical_object_types_dict.c.physical_object_function_id.in_(
                select(physical_object_functions_cte.c.physical_object_function_id)
            )
        )
    if service_type_id is not None and urban_function_id is not None:
        raise EntityNotFoundByParams("service type and urban function", service_type_id, urban_function_id)
    if service_type_id is not None:
        public_urban_objects_query = public_urban_objects_query.where(
            services_data.c.service_type_id == service_type_id
        )
        scenario_urban_objects_query = scenario_urban_objects_query.where(
            (projects_services_data.c.service_type_id == service_type_id)
            | (services_data.c.service_type_id == service_type_id)
        )
    elif urban_function_id is not None:
        urban_functions_cte = (
            select(
                urban_functions_dict.c.urban_function_id,
                urban_functions_dict.c.parent_urban_function_id,
            )
            .where(urban_functions_dict.c.urban_function_id == urban_function_id)
            .cte(recursive=True)
        )
        urban_functions_cte = urban_functions_cte.union_all(
            select(
                urban_functions_dict.c.urban_function_id,
                urban_functions_dict.c.parent_urban_function_id,
            ).join(
                urban_functions_cte,
                urban_functions_dict.c.parent_urban_function_id == urban_functions_cte.c.urban_function_id,
            )
        )
        public_urban_objects_query = public_urban_objects_query.where(
            service_types_dict.c.urban_function_id.in_(select(urban_functions_cte))
        )
        scenario_urban_objects_query = scenario_urban_objects_query.where(
            service_types_dict.c.urban_function_id.in_(select(urban_functions_cte))
        )

    # Получаем все объекты из public.urban_objects_data
    public_objects = []
    for row in (await conn.execute(public_urban_objects_query)).mappings().all():
        public_objects.append(
            {
                "object_geometry_id": row.object_geometry_id,
                "territory_id": row.territory_id,
                "territory_name": row.territory_name,
                "geometry": row.geometry,
                "centre_point": row.centre_point,
                "address": row.address,
                "osm_id": row.osm_id,
                "physical_object": {
                    "physical_object_id": row.physical_object_id,
                    "physical_object_type": {
                        "id": row.physical_object_type_id,
                        "name": row.physical_object_type_name,
                    },
                    "name": row.physical_object_name,
                    "living_building": (
                        {
                            "id": row.living_building_id,
                            "living_area": row.living_area,
                            "properties": row.living_building_properties,
                        }
                        if row.living_building_id is not None
                        else None
                    ),
                    "properties": row.physical_object_properties,
                    "is_scenario_object": False,
                },
                "service": (
                    {
                        "service_id": row.service_id,
                        "service_type": {"id": row.service_type_id, "name": row.service_type_name},
                        "territory_type": (
                            {"id": row.territory_type_id, "name": row.territory_type_name}
                            if row.territory_type_id is not None
                            else None
                        ),
                        "name": row.service_name,
                        "capacity_real": row.capacity_real,
                        "properties": row.service_properties,
                        "is_scenario_object": False,
                    }
                    if row.service_id
                    else None
                ),
                "is_scenario_object": False,
            }
        )

    # Получаем все объекты из user_projects.urban_objects_data
    scenario_objects = []
    for row in (await conn.execute(scenario_urban_objects_query)).mappings().all():
        is_scenario_geometry = row.object_geometry_id is not None and row.public_object_geometry_id is None
        is_scenario_physical_object = row.physical_object_id is not None and row.public_physical_object_id is None
        is_scenario_service = row.service_id is not None and row.public_service_id is None

        scenario_objects.append(
            {
                "object_geometry_id": row.object_geometry_id or row.public_object_geometry_id,
                "territory_id": row.territory_id,
                "territory_name": row.territory_name,
                "geometry": row.geometry if is_scenario_geometry else row.public_geometry,
                "centre_point": row.centre_point if is_scenario_geometry else row.public_centre_point,
                "address": row.address if is_scenario_geometry else row.public_address,
                "osm_id": row.osm_id if is_scenario_geometry else row.public_osm_id,
                "physical_object": {
                    "physical_object_id": row.physical_object_id or row.public_physical_object_id,
                    "physical_object_type": {
                        "id": row.physical_object_type_id,
                        "name": row.physical_object_type_name,
                    },
                    "name": (
                        row.physical_object_name if is_scenario_physical_object else row.public_physical_object_name
                    ),
                    "living_building": (
                        {
                            "id": (
                                row.living_building_id if is_scenario_physical_object else row.public_living_building_id
                            ),
                            "living_area": row.living_area if is_scenario_physical_object else row.public_living_area,
                            "properties": (
                                row.living_building_properties
                                if is_scenario_physical_object
                                else row.public_living_building_properties
                            ),
                        }
                        if row.living_building_id or row.public_living_building_id
                        else None
                    ),
                    "properties": (
                        row.physical_object_properties
                        if is_scenario_physical_object
                        else row.public_physical_object_properties
                    ),
                    "is_scenario_object": is_scenario_physical_object,
                },
                "service": (
                    {
                        "service_id": row.service_id or row.public_service_id,
                        "service_type": {"id": row.service_type_id, "name": row.service_type_name},
                        "territory_type": (
                            {"id": row.territory_type_id, "name": row.territory_type_name}
                            if row.territory_type_id is not None
                            else None
                        ),
                        "name": row.service_name if is_scenario_service else row.public_service_name,
                        "capacity_real": row.capacity_real if is_scenario_service else row.public_capacity_real,
                        "properties": row.service_properties if is_scenario_service else row.public_service_properties,
                        "is_scenario_object": is_scenario_service,
                    }
                    if row.service_id or row.public_service_id
                    else None
                ),
                "is_scenario_object": is_scenario_geometry,
            }
        )

    def initialize_group(group, obj, is_scenario_geometry):
        group.update(
            {
                "object_geometry_id": obj["object_geometry_id"],
                "territory_id": obj.get("territory_id"),
                "territory_name": obj.get("territory_name"),
                "geometry": obj.get("geometry"),
                "centre_point": obj.get("centre_point"),
                "address": obj.get("address"),
                "osm_id": obj.get("osm_id"),
                "is_scenario_object": is_scenario_geometry,
            }
        )

    def add_physical_object(group, obj):
        phys_obj_id = obj["physical_object"]["physical_object_id"]
        is_scenario_physical_object = obj["physical_object"]["is_scenario_object"]
        existing_phys_obj = group["physical_objects"].get(phys_obj_id)
        key = phys_obj_id if not is_scenario_physical_object else f"scenario_{phys_obj_id}"
        if existing_phys_obj is None:
            group["physical_objects"][key] = obj["physical_object"]

    def add_service(group, obj):
        service_id = obj["service"]["service_id"]
        is_scenario_service = obj["service"]["is_scenario_object"]
        existing_service = group["services"].get(service_id)
        key = service_id if not is_scenario_service else f"scenario_{service_id}"
        if existing_service is None:
            group["services"][key] = obj["service"]

    grouped_objects = defaultdict(lambda: {"physical_objects": defaultdict(dict), "services": defaultdict(dict)})

    for obj in public_objects + scenario_objects:
        geometry_id = obj["object_geometry_id"]
        is_scenario_geometry = obj["is_scenario_object"]
        key = geometry_id if not is_scenario_geometry else f"scenario_{geometry_id}"

        if key not in grouped_objects:
            initialize_group(grouped_objects[key], obj, is_scenario_geometry)

        add_physical_object(grouped_objects[key], obj)
        if obj["service"] is not None:
            add_service(grouped_objects[key], obj)

    for key, group in grouped_objects.items():
        group["physical_objects"] = list(group["physical_objects"].values())
        group["services"] = list(group["services"].values())

    return [ScenarioGeometryWithAllObjectsDTO(**group) for group in grouped_objects.values()]


async def get_context_geometries_by_scenario_id_from_db(
    conn: AsyncConnection,
    scenario_id: int,
    user_id: str,
    physical_object_id: int | None,
    service_id: int | None,
) -> list[ObjectGeometryDTO]:
    """Get list of geometries for 'context' of the project territory."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id and not project.public:
        raise AccessDeniedError(project_id, "project")

    context_territories = select(
        territories_data.c.territory_id,
        territories_data.c.geometry,
    ).where(territories_data.c.territory_id.in_(project.properties["context"]))
    unified_geometry = select(ST_Union(context_territories.c.geometry)).scalar_subquery()
    all_descendants = (
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        )
        .where(territories_data.c.territory_id.in_(select(context_territories.c.territory_id)))
        .cte(name="all_descendants", recursive=True)
    )
    all_descendants = all_descendants.union_all(
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        ).select_from(
            territories_data.join(
                all_descendants,
                territories_data.c.parent_id == all_descendants.c.territory_id,
            )
        )
    )
    all_ancestors = (
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        )
        .where(territories_data.c.territory_id.in_(select(context_territories.c.territory_id)))
        .cte(name="all_ancestors", recursive=True)
    )
    all_ancestors = all_ancestors.union_all(
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        ).select_from(
            territories_data.join(
                all_ancestors,
                territories_data.c.territory_id == all_ancestors.c.parent_id,
            )
        )
    )
    all_related_territories = (
        select(all_descendants.c.territory_id).union(select(all_ancestors.c.territory_id)).subquery()
    )

    objects_intersecting = (
        select(object_geometries_data.c.object_geometry_id)
        .where(
            object_geometries_data.c.territory_id.in_(select(all_related_territories)),
            ST_Intersects(object_geometries_data.c.geometry, unified_geometry),
        )
        .subquery()
    )

    # Step 2. Find all the geometries in `public` schema for `intersecting_territories`
    statement = (
        select(
            object_geometries_data.c.object_geometry_id,
            object_geometries_data.c.territory_id,
            territories_data.c.name.label("territory_name"),
            object_geometries_data.c.address,
            object_geometries_data.c.osm_id,
            cast(ST_AsGeoJSON(ST_Intersection(object_geometries_data.c.geometry, unified_geometry)), JSONB).label(
                "geometry"
            ),
            cast(
                ST_AsGeoJSON(ST_Centroid(ST_Intersection(object_geometries_data.c.geometry, unified_geometry))),
                JSONB,
            ).label("centre_point"),
            object_geometries_data.c.created_at,
            object_geometries_data.c.updated_at,
        )
        .select_from(
            object_geometries_data.join(
                territories_data,
                territories_data.c.territory_id == object_geometries_data.c.territory_id,
            )
            .join(
                urban_objects_data,
                urban_objects_data.c.object_geometry_id == object_geometries_data.c.object_geometry_id,
            )
            .join(
                physical_objects_data,
                physical_objects_data.c.physical_object_id == urban_objects_data.c.physical_object_id,
            )
            .outerjoin(services_data, services_data.c.service_id == urban_objects_data.c.service_id)
        )
        .where(object_geometries_data.c.object_geometry_id.in_(select(objects_intersecting)))
        .distinct()
    )

    # Условия фильтрации для объектов
    if physical_object_id is not None:
        statement = statement.where(physical_objects_data.c.physical_object_id == physical_object_id)
    if service_id is not None:
        statement = statement.where(services_data.c.service_id == service_id)

    result = (await conn.execute(statement)).mappings().all()

    return [ObjectGeometryDTO(**row) for row in result]


async def get_context_geometries_with_all_objects_by_scenario_id_from_db(
    conn: AsyncConnection,
    scenario_id: int,
    user_id: str,
    physical_object_type_id: int | None,
    service_type_id: int | None,
    physical_object_function_id: int | None,
    urban_function_id: int | None,
) -> list[GeometryWithAllObjectsDTO]:
    """Get geometries with lists of physical objects and services for 'context' of the project territory."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id and not project.public:
        raise AccessDeniedError(project_id, "project")

    context_territories = select(
        territories_data.c.territory_id,
        territories_data.c.geometry,
    ).where(territories_data.c.territory_id.in_(project.properties["context"]))
    unified_geometry = select(ST_Union(context_territories.c.geometry)).scalar_subquery()
    all_descendants = (
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        )
        .where(territories_data.c.territory_id.in_(select(context_territories.c.territory_id)))
        .cte(name="all_descendants", recursive=True)
    )
    all_descendants = all_descendants.union_all(
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        ).select_from(
            territories_data.join(
                all_descendants,
                territories_data.c.parent_id == all_descendants.c.territory_id,
            )
        )
    )
    all_ancestors = (
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        )
        .where(territories_data.c.territory_id.in_(select(context_territories.c.territory_id)))
        .cte(name="all_ancestors", recursive=True)
    )
    all_ancestors = all_ancestors.union_all(
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        ).select_from(
            territories_data.join(
                all_ancestors,
                territories_data.c.territory_id == all_ancestors.c.parent_id,
            )
        )
    )
    all_related_territories = (
        select(all_descendants.c.territory_id).union(select(all_ancestors.c.territory_id)).subquery()
    )

    objects_intersecting = (
        select(object_geometries_data.c.object_geometry_id)
        .where(
            object_geometries_data.c.territory_id.in_(select(all_related_territories)),
            ST_Intersects(object_geometries_data.c.geometry, unified_geometry),
        )
        .subquery()
    )

    # Шаг 2: Собрать все записи из public.urban_objects_data по собранным public_urban_object_id
    statement = (
        select(
            physical_objects_data.c.physical_object_id,
            physical_object_types_dict.c.physical_object_type_id,
            physical_object_types_dict.c.name.label("physical_object_type_name"),
            physical_objects_data.c.name.label("physical_object_name"),
            physical_objects_data.c.properties.label("physical_object_properties"),
            living_buildings_data.c.living_building_id,
            living_buildings_data.c.living_area,
            living_buildings_data.c.properties.label("living_building_properties"),
            object_geometries_data.c.object_geometry_id,
            territories_data.c.territory_id,
            territories_data.c.name.label("territory_name"),
            object_geometries_data.c.address,
            object_geometries_data.c.osm_id,
            cast(ST_AsGeoJSON(ST_Intersection(object_geometries_data.c.geometry, unified_geometry)), JSONB).label(
                "geometry"
            ),
            cast(
                ST_AsGeoJSON(ST_Centroid(ST_Intersection(object_geometries_data.c.geometry, unified_geometry))),
                JSONB,
            ).label("centre_point"),
            services_data.c.service_id,
            services_data.c.name.label("service_name"),
            services_data.c.capacity_real,
            services_data.c.properties.label("service_properties"),
            service_types_dict.c.service_type_id,
            service_types_dict.c.name.label("service_type_name"),
            territory_types_dict.c.territory_type_id,
            territory_types_dict.c.name.label("territory_type_name"),
        )
        .select_from(
            object_geometries_data.join(
                territories_data,
                territories_data.c.territory_id == object_geometries_data.c.territory_id,
            )
            .join(
                urban_objects_data,
                urban_objects_data.c.object_geometry_id == object_geometries_data.c.object_geometry_id,
            )
            .join(
                physical_objects_data,
                physical_objects_data.c.physical_object_id == urban_objects_data.c.physical_object_id,
            )
            .outerjoin(services_data, services_data.c.service_id == urban_objects_data.c.service_id)
            .join(
                physical_object_types_dict,
                physical_object_types_dict.c.physical_object_type_id == physical_objects_data.c.physical_object_type_id,
            )
            .outerjoin(
                service_types_dict,
                service_types_dict.c.service_type_id == services_data.c.service_type_id,
            )
            .outerjoin(
                territory_types_dict,
                territory_types_dict.c.territory_type_id == services_data.c.territory_type_id,
            )
            .outerjoin(
                living_buildings_data,
                living_buildings_data.c.physical_object_id == physical_objects_data.c.physical_object_id,
            )
        )
        .where(object_geometries_data.c.object_geometry_id.in_(select(objects_intersecting)))
        .distinct()
    )

    # Условия фильтрации для объектов
    if physical_object_type_id is not None and physical_object_function_id is not None:
        raise EntityNotFoundByParams(
            "physical object type and function", physical_object_type_id, physical_object_function_id
        )
    if physical_object_type_id is not None:
        statement = statement.where(services_data.c.service_type_id == service_type_id)
    elif physical_object_function_id is not None:
        physical_object_functions_cte = (
            select(
                physical_object_functions_dict.c.physical_object_function_id,
                physical_object_functions_dict.c.parent_id,
            )
            .where(physical_object_functions_dict.c.physical_object_function_id == physical_object_function_id)
            .cte(recursive=True)
        )
        physical_object_functions_cte = physical_object_functions_cte.union_all(
            select(
                physical_object_functions_dict.c.physical_object_function_id,
                physical_object_functions_dict.c.parent_id,
            ).join(
                physical_object_functions_cte,
                physical_object_functions_dict.c.parent_id
                == physical_object_functions_cte.c.physical_object_function_id,
            )
        )
        statement = statement.where(
            physical_object_types_dict.c.physical_object_function_id.in_(
                select(physical_object_functions_cte.c.physical_object_function_id)
            )
        )
    if service_type_id is not None and urban_function_id is not None:
        raise EntityNotFoundByParams("service type and urban function", service_type_id, urban_function_id)
    if service_type_id is not None:
        statement = statement.where(services_data.c.service_type_id == service_type_id)
    elif urban_function_id is not None:
        urban_functions_cte = (
            select(
                urban_functions_dict.c.urban_function_id,
                urban_functions_dict.c.parent_urban_function_id,
            )
            .where(urban_functions_dict.c.urban_function_id == urban_function_id)
            .cte(recursive=True)
        )
        urban_functions_cte = urban_functions_cte.union_all(
            select(
                urban_functions_dict.c.urban_function_id,
                urban_functions_dict.c.parent_urban_function_id,
            ).join(
                urban_functions_cte,
                urban_functions_dict.c.parent_urban_function_id == urban_functions_cte.c.urban_function_id,
            )
        )
        statement = statement.where(service_types_dict.c.urban_function_id.in_(select(urban_functions_cte)))

    urban_objects = []
    for row in (await conn.execute(statement)).mappings().all():
        urban_objects.append(
            {
                "object_geometry_id": row.object_geometry_id,
                "territory_id": row.territory_id,
                "territory_name": row.territory_name,
                "geometry": row.geometry,
                "centre_point": row.centre_point,
                "address": row.address,
                "osm_id": row.osm_id,
                "physical_object": {
                    "physical_object_id": row.physical_object_id,
                    "physical_object_type": {
                        "id": row.physical_object_type_id,
                        "name": row.physical_object_type_name,
                    },
                    "name": row.physical_object_name,
                    "living_building": (
                        {
                            "id": row.living_building_id,
                            "living_area": row.living_area,
                            "properties": row.living_building_properties,
                        }
                        if row.living_building_id is not None
                        else None
                    ),
                    "properties": row.physical_object_properties,
                },
                "service": (
                    {
                        "service_id": row.service_id,
                        "service_type": {"id": row.service_type_id, "name": row.service_type_name},
                        "territory_type": (
                            {"id": row.territory_type_id, "name": row.territory_type_name}
                            if row.territory_type_id is not None
                            else None
                        ),
                        "name": row.service_name,
                        "capacity_real": row.capacity_real,
                        "properties": row.service_properties,
                    }
                    if row.service_id
                    else None
                ),
            }
        )

    def initialize_group(group, obj):
        group.update(
            {
                "object_geometry_id": obj["object_geometry_id"],
                "territory_id": obj.get("territory_id"),
                "territory_name": obj.get("territory_name"),
                "geometry": obj.get("geometry"),
                "centre_point": obj.get("centre_point"),
                "address": obj.get("address"),
                "osm_id": obj.get("osm_id"),
            }
        )

    def add_physical_object(group, obj):
        phys_obj_id = obj["physical_object"]["physical_object_id"]
        existing_phys_obj = group["physical_objects"].get(phys_obj_id)
        if existing_phys_obj is None:
            group["physical_objects"][phys_obj_id] = obj["physical_object"]

    def add_service(group, obj):
        service_id = obj["service"]["service_id"]
        existing_service = group["services"].get(service_id)
        if existing_service is None:
            group["services"][service_id] = obj["service"]

    grouped_objects = defaultdict(lambda: {"physical_objects": defaultdict(dict), "services": defaultdict(dict)})

    for obj in urban_objects:
        geometry_id = obj["object_geometry_id"]
        if geometry_id not in grouped_objects:
            initialize_group(grouped_objects[geometry_id], obj)

        add_physical_object(grouped_objects[geometry_id], obj)
        if obj["service"] is not None:
            add_service(grouped_objects[geometry_id], obj)

    for _, group in grouped_objects.items():
        group["physical_objects"] = list(group["physical_objects"].values())
        group["services"] = list(group["services"].values())

    return [GeometryWithAllObjectsDTO(**group) for group in grouped_objects.values()]


async def get_scenario_object_geometry_by_id_from_db(
    conn: AsyncConnection, object_geometry_id: int
) -> ScenarioGeometryDTO:
    """Get scenario object geometry by identifier."""

    statement = (
        select(
            projects_object_geometries_data.c.object_geometry_id,
            projects_object_geometries_data.c.territory_id,
            territories_data.c.name.label("territory_name"),
            projects_object_geometries_data.c.address,
            projects_object_geometries_data.c.osm_id,
            cast(ST_AsGeoJSON(projects_object_geometries_data.c.geometry), JSONB).label("geometry"),
            cast(ST_AsGeoJSON(projects_object_geometries_data.c.centre_point), JSONB).label("centre_point"),
            projects_object_geometries_data.c.created_at,
            projects_object_geometries_data.c.updated_at,
            literal(True).label("is_scenario_object"),
        )
        .select_from(
            projects_object_geometries_data.join(
                territories_data,
                territories_data.c.territory_id == projects_object_geometries_data.c.territory_id,
            )
        )
        .where(projects_object_geometries_data.c.object_geometry_id == object_geometry_id)
        .distinct()
    )
    result = (await conn.execute(statement)).mappings().one_or_none()
    if result is None:
        raise EntityNotFoundById(object_geometry_id, "scenario object geometry")

    return ScenarioGeometryDTO(**result)


async def put_object_geometry_to_db(
    conn: AsyncConnection,
    object_geometry: ObjectGeometriesPut,
    scenario_id: int,
    object_geometry_id: int,
    is_scenario_object: bool,
    user_id: str,
) -> ScenarioGeometryDTO:
    """Update scenario object geometry by all its attributes."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id:
        raise AccessDeniedError(project_id, "project")

    if is_scenario_object:
        statement = select(projects_object_geometries_data.c.object_geometry_id).where(
            projects_object_geometries_data.c.object_geometry_id == object_geometry_id
        )
    else:
        statement = select(object_geometries_data.c.object_geometry_id).where(
            object_geometries_data.c.object_geometry_id == object_geometry_id
        )
    requested_geometry = (await conn.execute(statement)).scalar_one_or_none()
    if requested_geometry is None:
        raise EntityNotFoundById(object_geometry_id, "object geometry")

    if not is_scenario_object:
        statement = (
            select(projects_object_geometries_data.c.object_geometry_id)
            .select_from(
                projects_urban_objects_data.join(
                    projects_object_geometries_data,
                    projects_object_geometries_data.c.object_geometry_id
                    == projects_urban_objects_data.c.object_geometry_id,
                )
            )
            .where(
                projects_urban_objects_data.c.scenario_id == scenario_id,
                projects_object_geometries_data.c.public_object_geometry_id == object_geometry_id,
            )
        )
        public_object_geometry = (await conn.execute(statement)).scalar_one_or_none()
        if public_object_geometry is not None:
            raise EntityAlreadyExists("scenario object geometry", object_geometry_id)

    statement = select(territories_data.c.territory_id).where(
        territories_data.c.territory_id == object_geometry.territory_id
    )
    territory = (await conn.execute(statement)).scalar_one_or_none()
    if territory is None:
        raise EntityNotFoundById(object_geometry.territory_id, "territory")

    if is_scenario_object:
        statement = (
            update(projects_object_geometries_data)
            .where(projects_object_geometries_data.c.object_geometry_id == object_geometry_id)
            .values(
                territory_id=object_geometry.territory_id,
                geometry=ST_GeomFromText(str(object_geometry.geometry.as_shapely_geometry()), text("4326")),
                centre_point=ST_GeomFromText(str(object_geometry.centre_point.as_shapely_geometry()), text("4326")),
                address=object_geometry.address,
                osm_id=object_geometry.osm_id,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(projects_object_geometries_data.c.object_geometry_id)
        )
        updated_object_geometry_id = (await conn.execute(statement)).scalar_one()
    else:
        statement = (
            insert(projects_object_geometries_data)
            .values(
                public_object_geometry_id=object_geometry_id,
                territory_id=object_geometry.territory_id,
                geometry=ST_GeomFromText(str(object_geometry.geometry.as_shapely_geometry()), text("4326")),
                centre_point=ST_GeomFromText(str(object_geometry.centre_point.as_shapely_geometry()), text("4326")),
                address=object_geometry.address,
                osm_id=object_geometry.osm_id,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(projects_object_geometries_data.c.object_geometry_id)
        )
        updated_object_geometry_id = (await conn.execute(statement)).scalar_one()

        project_geometry = (
            select(projects_territory_data.c.geometry).where(projects_territory_data.c.project_id == project.project_id)
        ).alias("project_geometry")

        public_urban_object_ids = (
            select(projects_urban_objects_data.c.public_urban_object_id.label("urban_object_id"))
            .where(
                projects_urban_objects_data.c.scenario_id == scenario_id,
                projects_urban_objects_data.c.public_urban_object_id.is_not(None),
            )
            .alias("public_urban_object_ids")
        )

        statement = (
            select(urban_objects_data)
            .select_from(
                urban_objects_data.join(
                    object_geometries_data,
                    object_geometries_data.c.object_geometry_id == urban_objects_data.c.object_geometry_id,
                )
            )
            .where(
                urban_objects_data.c.object_geometry_id == object_geometry_id,
                urban_objects_data.c.urban_object_id.not_in(select(public_urban_object_ids.c.urban_object_id)),
                ST_Within(object_geometries_data.c.geometry, select(project_geometry).scalar_subquery()),
            )
        )
        urban_objects = (await conn.execute(statement)).mappings().all()
        if urban_objects:
            await conn.execute(
                insert(projects_urban_objects_data).values(
                    [
                        {
                            "public_urban_object_id": row.urban_object_id,
                            "scenario_id": scenario_id,
                        }
                        for row in urban_objects
                    ]
                )
            )
            await conn.execute(
                insert(projects_urban_objects_data).values(
                    [
                        {
                            "public_physical_object_id": row.physical_object_id,
                            "public_service_id": row.service_id,
                            "object_geometry_id": updated_object_geometry_id,
                            "scenario_id": scenario_id,
                        }
                        for row in urban_objects
                    ]
                )
            )
        await conn.execute(
            (
                update(projects_urban_objects_data)
                .where(projects_urban_objects_data.c.public_object_geometry_id == object_geometry_id)
                .values(object_geometry_id=updated_object_geometry_id, public_object_geometry_id=None)
            )
        )

    await conn.commit()

    return await get_scenario_object_geometry_by_id_from_db(conn, updated_object_geometry_id)


async def patch_object_geometry_to_db(
    conn: AsyncConnection,
    object_geometry: ObjectGeometriesPatch,
    scenario_id: int,
    object_geometry_id: int,
    is_scenario_object: bool,
    user_id: str,
) -> ScenarioGeometryDTO:
    """Update scenario object geometry by only given attributes."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id:
        raise AccessDeniedError(project_id, "project")

    if is_scenario_object:
        statement = select(projects_object_geometries_data).where(
            projects_object_geometries_data.c.object_geometry_id == object_geometry_id
        )
    else:
        statement = select(object_geometries_data).where(
            object_geometries_data.c.object_geometry_id == object_geometry_id
        )
    requested_geometry = (await conn.execute(statement)).mappings().one_or_none()
    if requested_geometry is None:
        raise EntityNotFoundById(object_geometry_id, "object geometry")

    if not is_scenario_object:
        statement = (
            select(projects_object_geometries_data.c.object_geometry_id)
            .select_from(
                projects_urban_objects_data.join(
                    projects_object_geometries_data,
                    projects_object_geometries_data.c.object_geometry_id
                    == projects_urban_objects_data.c.object_geometry_id,
                )
            )
            .where(
                projects_urban_objects_data.c.scenario_id == scenario_id,
                projects_object_geometries_data.c.public_object_geometry_id == object_geometry_id,
            )
        )
        public_object_geometry = (await conn.execute(statement)).scalar_one_or_none()
        if public_object_geometry is not None:
            raise EntityAlreadyExists("scenario object geometry", object_geometry_id)

    if object_geometry.territory_id is not None:
        statement = select(territories_data.c.territory_id).where(
            territories_data.c.territory_id == object_geometry.territory_id
        )
        territory = (await conn.execute(statement)).scalar_one_or_none()
        if territory is None:
            raise EntityNotFoundById(object_geometry.territory_id, "territory")

    values_to_update = {}
    for k, v in object_geometry.model_dump(exclude_unset=True).items():
        if k == "geometry":
            values_to_update.update(
                {"geometry": ST_GeomFromText(str(object_geometry.geometry.as_shapely_geometry()), text("4326"))}
            )
        elif k == "centre_point":
            values_to_update.update(
                {"centre_point": ST_GeomFromText(str(object_geometry.centre_point.as_shapely_geometry()), text("4326"))}
            )
        else:
            values_to_update.update({k: v})

    if is_scenario_object:
        statement = (
            update(projects_object_geometries_data)
            .where(projects_object_geometries_data.c.object_geometry_id == object_geometry_id)
            .values(updated_at=datetime.now(timezone.utc), **values_to_update)
            .returning(projects_object_geometries_data.c.object_geometry_id)
        )
        updated_object_geometry_id = (await conn.execute(statement)).scalar_one()
    else:
        statement = (
            insert(projects_object_geometries_data)
            .values(
                public_object_geometry_id=object_geometry_id,
                territory_id=values_to_update.get("territory_id", requested_geometry.territory_id),
                geometry=values_to_update.get("geometry", requested_geometry.geometry),
                centre_point=values_to_update.get("centre_point", requested_geometry.centre_point),
                address=values_to_update.get("address", requested_geometry.address),
                osm_id=values_to_update.get("osm_id", requested_geometry.osm_id),
            )
            .returning(projects_object_geometries_data.c.object_geometry_id)
        )
        updated_object_geometry_id = (await conn.execute(statement)).scalar_one()

        project_geometry = (
            select(projects_territory_data.c.geometry).where(projects_territory_data.c.project_id == project.project_id)
        ).alias("project_geometry")

        public_urban_object_ids = (
            select(projects_urban_objects_data.c.public_urban_object_id.label("urban_object_id"))
            .where(
                projects_urban_objects_data.c.scenario_id == scenario_id,
                projects_urban_objects_data.c.public_urban_object_id.is_not(None),
            )
            .alias("public_urban_object_ids")
        )

        statement = (
            select(urban_objects_data)
            .select_from(
                urban_objects_data.join(
                    object_geometries_data,
                    object_geometries_data.c.object_geometry_id == urban_objects_data.c.object_geometry_id,
                )
            )
            .where(
                urban_objects_data.c.object_geometry_id == object_geometry_id,
                urban_objects_data.c.urban_object_id.not_in(select(public_urban_object_ids.c.urban_object_id)),
                ST_Within(object_geometries_data.c.geometry, select(project_geometry).scalar_subquery()),
            )
        )
        urban_objects = (await conn.execute(statement)).mappings().all()
        if urban_objects:
            await conn.execute(
                insert(projects_urban_objects_data).values(
                    [
                        {
                            "public_urban_object_id": row.urban_object_id,
                            "scenario_id": scenario_id,
                        }
                        for row in urban_objects
                    ]
                )
            )
            await conn.execute(
                insert(projects_urban_objects_data).values(
                    [
                        {
                            "public_physical_object_id": row.physical_object_id,
                            "public_service_id": row.service_id,
                            "object_geometry_id": updated_object_geometry_id,
                            "scenario_id": scenario_id,
                        }
                        for row in urban_objects
                    ]
                )
            )
        await conn.execute(
            (
                update(projects_urban_objects_data)
                .where(projects_urban_objects_data.c.public_object_geometry_id == object_geometry_id)
                .values(object_geometry_id=updated_object_geometry_id, public_object_geometry_id=None)
            )
        )

    await conn.commit()

    return await get_scenario_object_geometry_by_id_from_db(conn, updated_object_geometry_id)


async def delete_object_geometry_in_db(
    conn: AsyncConnection,
    scenario_id: int,
    object_geometry_id: int,
    is_scenario_object: bool,
    user_id: str,
) -> dict:
    """Delete scenario physical object."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id:
        raise AccessDeniedError(project_id, "project")

    if is_scenario_object:
        statement = select(projects_object_geometries_data.c.object_geometry_id).where(
            projects_object_geometries_data.c.object_geometry_id == object_geometry_id
        )
    else:
        statement = select(object_geometries_data.c.object_geometry_id).where(
            object_geometries_data.c.object_geometry_id == object_geometry_id
        )
    requested_geometry = (await conn.execute(statement)).scalar_one_or_none()
    if requested_geometry is None:
        raise EntityNotFoundById(object_geometry_id, "object geometry")

    if is_scenario_object:
        statement = delete(projects_object_geometries_data).where(
            projects_object_geometries_data.c.object_geometry_id == object_geometry_id
        )
        await conn.execute(statement)
    else:
        statement = delete(projects_urban_objects_data).where(
            projects_urban_objects_data.c.public_object_geometry_id == object_geometry_id
        )
        await conn.execute(statement)

        project_geometry = (
            select(projects_territory_data.c.geometry).where(projects_territory_data.c.project_id == project.project_id)
        ).alias("project_geometry")

        public_urban_object_ids = (
            select(projects_urban_objects_data.c.public_urban_object_id.label("urban_object_id"))
            .where(
                projects_urban_objects_data.c.scenario_id == scenario_id,
                projects_urban_objects_data.c.public_urban_object_id.is_not(None),
            )
            .alias("public_urban_object_ids")
        )

        statement = (
            select(urban_objects_data)
            .select_from(
                urban_objects_data.join(
                    object_geometries_data,
                    object_geometries_data.c.object_geometry_id == urban_objects_data.c.object_geometry_id,
                )
            )
            .where(
                urban_objects_data.c.object_geometry_id == object_geometry_id,
                urban_objects_data.c.urban_object_id.not_in(select(public_urban_object_ids.c.urban_object_id)),
                ST_Within(object_geometries_data.c.geometry, select(project_geometry).scalar_subquery()),
            )
        )
        urban_objects = (await conn.execute(statement)).mappings().all()
        if urban_objects:
            await conn.execute(
                insert(projects_urban_objects_data).values(
                    [
                        {
                            "public_urban_object_id": row.urban_object_id,
                            "scenario_id": scenario_id,
                        }
                        for row in urban_objects
                    ]
                )
            )

    await conn.commit()

    return {"result": "ok"}
