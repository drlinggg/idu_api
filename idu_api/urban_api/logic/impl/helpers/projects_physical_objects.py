"""Projects physical objects internal logic is defined here."""

from datetime import datetime, timezone

from geoalchemy2.functions import ST_GeomFromText, ST_Intersects, ST_Union, ST_Within
from sqlalchemy import Integer, cast, delete, insert, literal, or_, select, text, update
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
    projects_territory_data,
    projects_urban_objects_data,
    scenarios_data,
    territories_data,
    urban_objects_data,
)
from idu_api.urban_api.dto import PhysicalObjectDataDTO, ScenarioPhysicalObjectDTO, ScenarioUrbanObjectDTO
from idu_api.urban_api.exceptions.logic.common import EntitiesNotFoundByIds, EntityAlreadyExists, EntityNotFoundById
from idu_api.urban_api.exceptions.logic.users import AccessDeniedError
from idu_api.urban_api.logic.impl.helpers.projects_urban_objects import get_scenario_urban_object_by_id_from_db
from idu_api.urban_api.schemas import PhysicalObjectsDataPatch, PhysicalObjectsDataPut, PhysicalObjectWithGeometryPost


async def get_physical_objects_by_scenario_id(
    conn: AsyncConnection,
    scenario_id: int,
    user_id: str,
    physical_object_type_id: int | None,
    physical_object_function_id: int | None,
) -> list[ScenarioPhysicalObjectDTO]:
    """Get physical objects by scenario identifier."""

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
            physical_object_functions_dict.c.physical_object_function_id,
            physical_object_functions_dict.c.name.label("physical_object_function_name"),
            physical_objects_data.c.name,
            physical_objects_data.c.properties,
            physical_objects_data.c.created_at,
            physical_objects_data.c.updated_at,
            living_buildings_data.c.living_building_id,
            living_buildings_data.c.living_area,
            living_buildings_data.c.properties.label("living_building_properties"),
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
            .join(
                physical_object_functions_dict,
                physical_object_functions_dict.c.physical_object_function_id
                == physical_object_types_dict.c.physical_object_function_id,
            )
            .outerjoin(
                living_buildings_data,
                living_buildings_data.c.physical_object_id == physical_objects_data.c.physical_object_id,
            )
        )
        .where(
            urban_objects_data.c.urban_object_id.not_in(select(public_urban_object_ids)),
            ST_Within(object_geometries_data.c.geometry, select(project_geometry).scalar_subquery()),
        )
    )

    # Условия фильтрации для public объектов
    if physical_object_type_id is not None:
        public_urban_objects_query = public_urban_objects_query.where(
            physical_objects_data.c.physical_object_type_id == physical_object_type_id
        )
    if physical_object_function_id is not None:
        public_urban_objects_query = public_urban_objects_query.where(
            physical_object_types_dict.c.physical_object_function_id == physical_object_function_id
        )

    # Получаем все объекты из public.urban_objects_data
    public_objects = []
    for row in (await conn.execute(public_urban_objects_query)).mappings().all():
        public_objects.append(
            {
                "physical_object_id": row.physical_object_id,
                "physical_object_type_id": row.physical_object_type_id,
                "physical_object_type_name": row.physical_object_type_name,
                "physical_object_function_id": row.physical_object_function_id,
                "physical_object_function_name": row.physical_object_function_name,
                "living_building_id": row.living_building_id,
                "living_area": row.living_area,
                "living_building_properties": row.living_building_properties,
                "name": row.name,
                "properties": row.properties,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "is_scenario_object": False,
            }
        )

    # Шаг 3: Собрать все записи из user_projects.urban_objects_data для данного сценария
    scenario_urban_objects_query = (
        select(
            projects_physical_objects_data.c.physical_object_id,
            physical_object_types_dict.c.physical_object_type_id,
            physical_object_types_dict.c.name.label("physical_object_type_name"),
            physical_object_functions_dict.c.physical_object_function_id,
            physical_object_functions_dict.c.name.label("physical_object_function_name"),
            projects_physical_objects_data.c.name,
            projects_physical_objects_data.c.properties,
            projects_physical_objects_data.c.created_at,
            projects_physical_objects_data.c.updated_at,
            physical_objects_data.c.physical_object_id.label("public_physical_object_id"),
            physical_objects_data.c.name.label("public_name"),
            physical_objects_data.c.properties.label("public_properties"),
            physical_objects_data.c.created_at.label("public_created_at"),
            physical_objects_data.c.updated_at.label("public_updated_at"),
            projects_living_buildings_data.c.living_building_id,
            projects_living_buildings_data.c.living_area,
            living_buildings_data.c.properties.label("living_building_properties"),
            living_buildings_data.c.living_building_id.label("public_living_building_id"),
            living_buildings_data.c.living_area.label("public_living_area"),
            living_buildings_data.c.properties.label("public_living_building_properties"),
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
                physical_objects_data,
                physical_objects_data.c.physical_object_id == projects_urban_objects_data.c.public_physical_object_id,
            )
            .outerjoin(
                object_geometries_data,
                object_geometries_data.c.object_geometry_id == projects_urban_objects_data.c.public_object_geometry_id,
            )
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
                physical_object_functions_dict,
                physical_object_functions_dict.c.physical_object_function_id
                == physical_object_types_dict.c.physical_object_function_id,
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

    # Условия фильтрации для объектов user_projects
    if physical_object_type_id:
        scenario_urban_objects_query = scenario_urban_objects_query.where(
            (projects_physical_objects_data.c.physical_object_type_id == physical_object_type_id)
            | (physical_objects_data.c.physical_object_type_id == physical_object_type_id)
        )
    if physical_object_function_id is not None:
        scenario_urban_objects_query = scenario_urban_objects_query.where(
            physical_object_types_dict.c.physical_object_function_id == physical_object_function_id
        )

    # Получаем все объекты из user_projects.urban_objects_data
    scenario_objects = []
    for row in (await conn.execute(scenario_urban_objects_query)).mappings().all():
        is_scenario_physical_object = row.physical_object_id is not None and row.public_physical_object_id is None
        scenario_objects.append(
            {
                "physical_object_id": row.physical_object_id or row.public_physical_object_id,
                "physical_object_type_id": row.physical_object_type_id,
                "physical_object_type_name": row.physical_object_type_name,
                "physical_object_function_id": row.physical_object_function_id,
                "physical_object_function_name": row.physical_object_function_name,
                "name": row.name if is_scenario_physical_object else row.public_name,
                "living_building_id": (
                    row.living_building_id if is_scenario_physical_object else row.public_living_building_id
                ),
                "living_area": row.living_area if is_scenario_physical_object else row.public_living_area,
                "living_building_properties": (
                    row.living_building_properties
                    if is_scenario_physical_object
                    else row.public_living_building_properties
                ),
                "properties": row.properties if is_scenario_physical_object else row.public_properties,
                "created_at": row.created_at if is_scenario_physical_object else row.public_created_at,
                "updated_at": row.updated_at if is_scenario_physical_object else row.public_updated_at,
                "is_scenario_object": is_scenario_physical_object,
            }
        )

    grouped_objects = {}
    for obj in public_objects + scenario_objects:
        physical_object_id = obj["physical_object_id"]
        is_scenario_geometry = obj["is_scenario_object"]

        # Проверка и добавление физ объекта
        existing_entry = grouped_objects.get(physical_object_id)
        if existing_entry is None:
            grouped_objects[physical_object_id] = obj
        elif existing_entry.get("is_scenario_object") != is_scenario_geometry:
            grouped_objects[-physical_object_id] = obj

    return [ScenarioPhysicalObjectDTO(**row) for row in grouped_objects.values()]


async def get_context_physical_objects_by_scenario_id_from_db(
    conn: AsyncConnection,
    scenario_id: int,
    user_id: str,
    physical_object_type_id: int | None,
    physical_object_function_id: int | None,
) -> list[PhysicalObjectDataDTO]:
    """Get list of physical objects for 'context' of the project territory."""

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

    # Step 2. Find all the physical objects in `public` schema for `intersecting_territories`
    statement = (
        select(
            physical_objects_data.c.physical_object_id,
            physical_object_types_dict.c.physical_object_type_id,
            physical_object_types_dict.c.name.label("physical_object_type_name"),
            physical_object_functions_dict.c.physical_object_function_id,
            physical_object_functions_dict.c.name.label("physical_object_function_name"),
            physical_objects_data.c.name,
            physical_objects_data.c.properties,
            physical_objects_data.c.created_at,
            physical_objects_data.c.updated_at,
            living_buildings_data.c.living_building_id,
            living_buildings_data.c.living_area,
            living_buildings_data.c.properties.label("living_building_properties"),
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
            .join(
                physical_object_functions_dict,
                physical_object_functions_dict.c.physical_object_function_id
                == physical_object_types_dict.c.physical_object_function_id,
            )
            .outerjoin(
                living_buildings_data,
                living_buildings_data.c.physical_object_id == physical_objects_data.c.physical_object_id,
            )
        )
        .where(object_geometries_data.c.object_geometry_id.in_(select(objects_intersecting)))
        .distinct()
    )

    # Условия фильтрации для public объектов
    if physical_object_type_id is not None:
        statement = statement.where(physical_objects_data.c.physical_object_type_id == physical_object_type_id)
    if physical_object_function_id is not None:
        statement = statement.where(
            physical_object_types_dict.c.physical_object_function_id == physical_object_function_id
        )

    result = (await conn.execute(statement)).mappings().all()

    return [PhysicalObjectDataDTO(**row) for row in result]


async def get_scenario_physical_object_by_id_from_db(
    conn: AsyncConnection, physical_object_id: int
) -> ScenarioPhysicalObjectDTO:
    """Get scenario physical object by identifier."""

    statement = (
        select(
            projects_physical_objects_data.c.physical_object_id,
            physical_object_types_dict.c.physical_object_type_id,
            physical_object_types_dict.c.name.label("physical_object_type_name"),
            physical_object_functions_dict.c.physical_object_function_id,
            physical_object_functions_dict.c.name.label("physical_object_function_name"),
            projects_physical_objects_data.c.name,
            projects_physical_objects_data.c.properties,
            projects_physical_objects_data.c.created_at,
            projects_physical_objects_data.c.updated_at,
            literal(True).label("is_scenario_object"),
            projects_living_buildings_data.c.living_building_id,
            projects_living_buildings_data.c.living_area,
            projects_living_buildings_data.c.properties.label("living_building_properties"),
        )
        .select_from(
            projects_physical_objects_data.join(
                physical_object_types_dict,
                physical_object_types_dict.c.physical_object_type_id
                == projects_physical_objects_data.c.physical_object_type_id,
            )
            .join(
                physical_object_functions_dict,
                physical_object_functions_dict.c.physical_object_function_id
                == physical_object_types_dict.c.physical_object_function_id,
            )
            .outerjoin(
                projects_living_buildings_data,
                projects_living_buildings_data.c.physical_object_id
                == projects_physical_objects_data.c.physical_object_id,
            )
        )
        .where(projects_physical_objects_data.c.physical_object_id == physical_object_id)
        .distinct()
    )
    result = (await conn.execute(statement)).mappings().one_or_none()
    if result is None:
        raise EntityNotFoundById(physical_object_id, "scenario physical object")

    return ScenarioPhysicalObjectDTO(**result)


async def add_physical_object_with_geometry_to_db(
    conn: AsyncConnection,
    physical_object: PhysicalObjectWithGeometryPost,
    scenario_id: int,
    user_id: str,
) -> ScenarioUrbanObjectDTO:
    """Create scenario physical object with geometry."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id:
        raise AccessDeniedError(project_id, "project")

    statement = select(territories_data).where(territories_data.c.territory_id == physical_object.territory_id)
    territory = (await conn.execute(statement)).one_or_none()
    if territory is None:
        raise EntityNotFoundById(physical_object.territory_id, "territory")

    statement = select(physical_object_types_dict).where(
        physical_object_types_dict.c.physical_object_type_id == physical_object.physical_object_type_id
    )
    physical_object_type = (await conn.execute(statement)).one_or_none()
    if physical_object_type is None:
        raise EntityNotFoundById(physical_object.physical_object_type_id, "physical object type")

    statement = (
        insert(projects_physical_objects_data)
        .values(
            public_physical_object_id=None,
            physical_object_type_id=physical_object.physical_object_type_id,
            name=physical_object.name,
            properties=physical_object.properties,
        )
        .returning(projects_physical_objects_data.c.physical_object_id)
    )
    physical_object_id = (await conn.execute(statement)).scalar_one()

    statement = (
        insert(projects_object_geometries_data)
        .values(
            public_object_geometry_id=None,
            territory_id=physical_object.territory_id,
            geometry=ST_GeomFromText(str(physical_object.geometry.as_shapely_geometry()), text("4326")),
            centre_point=ST_GeomFromText(str(physical_object.centre_point.as_shapely_geometry()), text("4326")),
            address=physical_object.address,
            osm_id=physical_object.osm_id,
        )
        .returning(projects_object_geometries_data.c.object_geometry_id)
    )
    object_geometry_id = (await conn.execute(statement)).scalar_one()

    statement = (
        insert(projects_urban_objects_data)
        .values(scenario_id=scenario_id, physical_object_id=physical_object_id, object_geometry_id=object_geometry_id)
        .returning(urban_objects_data.c.urban_object_id)
    )
    urban_object_id = (await conn.execute(statement)).scalar_one_or_none()
    await conn.commit()

    return (await get_scenario_urban_object_by_id_from_db(conn, [urban_object_id]))[0]


async def put_physical_object_to_db(
    conn: AsyncConnection,
    physical_object: PhysicalObjectsDataPut,
    scenario_id: int,
    physical_object_id: int,
    is_scenario_object: bool,
    user_id: str,
) -> ScenarioPhysicalObjectDTO:
    """Update scenario physical object by all its attributes."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id:
        raise AccessDeniedError(project_id, "project")

    if is_scenario_object:
        statement = select(projects_physical_objects_data.c.physical_object_id).where(
            projects_physical_objects_data.c.physical_object_id == physical_object_id
        )
    else:
        statement = select(physical_objects_data.c.physical_object_id).where(
            physical_objects_data.c.physical_object_id == physical_object_id
        )
    requested_physical_object = (await conn.execute(statement)).scalar_one_or_none()
    if requested_physical_object is None:
        raise EntityNotFoundById(physical_object_id, "physical object")

    if not is_scenario_object:
        statement = (
            select(projects_physical_objects_data.c.physical_object_id)
            .select_from(
                projects_urban_objects_data.join(
                    projects_physical_objects_data,
                    projects_physical_objects_data.c.physical_object_id
                    == projects_urban_objects_data.c.physical_object_id,
                )
            )
            .where(
                projects_urban_objects_data.c.scenario_id == scenario_id,
                projects_physical_objects_data.c.public_physical_object_id == physical_object_id,
            )
        )
        public_physical_object = (await conn.execute(statement)).scalar_one_or_none()
        if public_physical_object is not None:
            raise EntityAlreadyExists("scenario physical object", physical_object_id)

    statement = select(physical_object_types_dict).where(
        physical_object_types_dict.c.physical_object_type_id == physical_object.physical_object_type_id
    )
    physical_object_type = (await conn.execute(statement)).one_or_none()
    if physical_object_type is None:
        raise EntityNotFoundById(physical_object.physical_object_type_id, "physical object type")

    if is_scenario_object:
        statement = (
            update(projects_physical_objects_data)
            .where(projects_physical_objects_data.c.physical_object_id == physical_object_id)
            .values(
                physical_object_type_id=physical_object.physical_object_type_id,
                name=physical_object.name,
                properties=physical_object.properties,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(projects_physical_objects_data.c.physical_object_id)
        )
        updated_physical_object_id = (await conn.execute(statement)).scalar_one()
    else:
        statement = (
            insert(projects_physical_objects_data)
            .values(
                public_physical_object_id=physical_object_id,
                physical_object_type_id=physical_object.physical_object_type_id,
                name=physical_object.name,
                properties=physical_object.properties,
            )
            .returning(projects_physical_objects_data.c.physical_object_id)
        )
        updated_physical_object_id = (await conn.execute(statement)).scalar_one()

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
                urban_objects_data.c.physical_object_id == physical_object_id,
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
                            "physical_object_id": updated_physical_object_id,
                            "public_service_id": row.service_id,
                            "public_object_geometry_id": row.object_geometry_id,
                            "scenario_id": scenario_id,
                        }
                        for row in urban_objects
                    ]
                )
            )
        await conn.execute(
            (
                update(projects_urban_objects_data)
                .where(projects_urban_objects_data.c.public_physical_object_id == physical_object_id)
                .values(physical_object_id=updated_physical_object_id, public_physical_object_id=None)
            )
        )

    await conn.commit()

    return await get_scenario_physical_object_by_id_from_db(conn, updated_physical_object_id)


async def patch_physical_object_to_db(
    conn: AsyncConnection,
    physical_object: PhysicalObjectsDataPatch,
    scenario_id: int,
    physical_object_id: int,
    is_scenario_object: bool,
    user_id: str,
) -> ScenarioPhysicalObjectDTO:
    """Update scenario physical object by only given attributes."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id:
        raise AccessDeniedError(project_id, "project")

    if is_scenario_object:
        statement = select(projects_physical_objects_data).where(
            projects_physical_objects_data.c.physical_object_id == physical_object_id
        )
    else:
        statement = select(physical_objects_data).where(
            physical_objects_data.c.physical_object_id == physical_object_id
        )
    requested_physical_object = (await conn.execute(statement)).mappings().one_or_none()
    if requested_physical_object is None:
        raise EntityNotFoundById(physical_object_id, "physical object")

    if not is_scenario_object:
        statement = (
            select(projects_physical_objects_data.c.physical_object_id)
            .select_from(
                projects_urban_objects_data.join(
                    projects_physical_objects_data,
                    projects_physical_objects_data.c.physical_object_id
                    == projects_urban_objects_data.c.physical_object_id,
                )
            )
            .where(
                projects_urban_objects_data.c.scenario_id == scenario_id,
                projects_physical_objects_data.c.public_physical_object_id == physical_object_id,
            )
        )
        public_physical_object = (await conn.execute(statement)).scalar_one_or_none()
        if public_physical_object is not None:
            raise EntityAlreadyExists("scenario physical object", physical_object_id)

    if physical_object.physical_object_type_id is not None:
        statement = select(physical_object_types_dict).where(
            physical_object_types_dict.c.physical_object_type_id == physical_object.physical_object_type_id
        )
        physical_object_type = (await conn.execute(statement)).one_or_none()
        if physical_object_type is None:
            raise EntityNotFoundById(physical_object.physical_object_type_id, "physical object type")

    values_to_update = {}
    for k, v in physical_object.model_dump(exclude_unset=True).items():
        values_to_update.update({k: v})

    if is_scenario_object:
        statement = (
            update(projects_physical_objects_data)
            .where(projects_physical_objects_data.c.physical_object_id == physical_object_id)
            .values(updated_at=datetime.now(timezone.utc), **values_to_update)
            .returning(projects_physical_objects_data.c.physical_object_id)
        )
        updated_physical_object_id = (await conn.execute(statement)).scalar_one()
    else:
        statement = (
            insert(projects_physical_objects_data)
            .values(
                public_physical_object_id=physical_object_id,
                physical_object_type_id=values_to_update.get(
                    "physical_object_type_id", requested_physical_object.physical_object_type_id
                ),
                name=values_to_update.get("name", requested_physical_object.name),
                properties=values_to_update.get("properties", requested_physical_object.properties),
            )
            .returning(projects_physical_objects_data.c.physical_object_id)
        )
        updated_physical_object_id = (await conn.execute(statement)).scalar_one()

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
                urban_objects_data.c.physical_object_id == physical_object_id,
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
                            "physical_object_id": updated_physical_object_id,
                            "public_service_id": row.service_id,
                            "public_object_geometry_id": row.object_geometry_id,
                            "scenario_id": scenario_id,
                        }
                        for row in urban_objects
                    ]
                )
            )
        await conn.execute(
            (
                update(projects_urban_objects_data)
                .where(projects_urban_objects_data.c.public_physical_object_id == physical_object_id)
                .values(physical_object_id=updated_physical_object_id, public_physical_object_id=None)
            )
        )

    await conn.commit()

    return await get_scenario_physical_object_by_id_from_db(conn, updated_physical_object_id)


async def delete_physical_object_in_db(
    conn: AsyncConnection,
    scenario_id: int,
    physical_object_id: int,
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
        statement = select(projects_physical_objects_data.c.physical_object_id).where(
            projects_physical_objects_data.c.physical_object_id == physical_object_id
        )
    else:
        statement = select(physical_objects_data.c.physical_object_id).where(
            physical_objects_data.c.physical_object_id == physical_object_id
        )
    requested_physical_object = (await conn.execute(statement)).scalar_one_or_none()
    if requested_physical_object is None:
        raise EntityNotFoundById(physical_object_id, "physical object")

    if is_scenario_object:
        statement = delete(projects_physical_objects_data).where(
            projects_physical_objects_data.c.physical_object_id == physical_object_id
        )
        await conn.execute(statement)
    else:
        statement = delete(projects_urban_objects_data).where(
            projects_urban_objects_data.c.public_physical_object_id == physical_object_id
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
                urban_objects_data.c.physical_object_id == physical_object_id,
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


async def update_physical_objects_by_function_id_to_db(
    conn: AsyncConnection,
    physical_objects: list[PhysicalObjectWithGeometryPost],
    scenario_id: int,
    user_id: str,
    physical_object_function_id: int,
) -> list[ScenarioUrbanObjectDTO]:
    """Delete all physical objects by physical object function identifier
    and upload new objects with the same function for given scenario."""

    statement = select(scenarios_data.c.project_id).where(scenarios_data.c.scenario_id == scenario_id)
    project_id = (await conn.execute(statement)).scalar_one_or_none()
    if project_id is None:
        raise EntityNotFoundById(scenario_id, "scenario")

    statement = select(projects_data).where(projects_data.c.project_id == project_id)
    project = (await conn.execute(statement)).mappings().one_or_none()
    if project.user_id != user_id:
        raise AccessDeniedError(project_id, "project")

    territories = set(phys_obj.territory_id for phys_obj in physical_objects)
    statement = select(territories_data.c.territory_id).where(territories_data.c.territory_id.in_(territories))
    result = (await conn.execute(statement)).scalars().all()
    if len(territories) > len(list(result)):
        raise EntitiesNotFoundByIds("territory")

    physical_object_types = set(phys_obj.physical_object_type_id for phys_obj in physical_objects)
    statement = select(physical_object_types_dict.c.physical_object_function_id).where(
        physical_object_types_dict.c.physical_object_type_id.in_(physical_object_types)
    )
    result = (await conn.execute(statement)).scalars().all()
    if len(physical_object_types) > len(list(result)):
        raise EntitiesNotFoundByIds("physical object type")
    if any(physical_object_function_id != function_id for function_id in result):
        raise ValueError("you can only upload physical objects with given physical object function!")

    project_geometry = (
        select(projects_territory_data.c.geometry).where(projects_territory_data.c.project_id == project.project_id)
    ).alias("project_geometry")

    territories_cte = (
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        )
        .where(territories_data.c.territory_id == project.territory_id)
        .cte(name="all_descendants", recursive=True)
    )
    territories_cte = territories_cte.union_all(
        select(
            territories_data.c.territory_id,
            territories_data.c.parent_id,
        ).select_from(
            territories_data.join(
                territories_cte,
                territories_data.c.parent_id == territories_cte.c.territory_id,
            )
        )
    )

    objects_intersecting = (
        select(object_geometries_data.c.object_geometry_id)
        .where(
            object_geometries_data.c.territory_id.in_(select(territories_cte.c.territory_id)),
            ST_Intersects(object_geometries_data.c.geometry, select(project_geometry).scalar_subquery()),
        )
        .subquery()
    )

    # Шаг 1: Получить все public_urban_object_id для данного scenario_id
    public_urban_object_ids = (
        select(projects_urban_objects_data.c.public_urban_object_id).where(
            projects_urban_objects_data.c.scenario_id == scenario_id,
            projects_urban_objects_data.c.public_urban_object_id.isnot(None),
        )
    ).alias("public_urban_object_ids")

    # Шаг 2: Собрать все записи из public.urban_objects_data по собранным public_urban_object_id
    public_urban_objects_query = (
        select(urban_objects_data.c.urban_object_id)
        .select_from(
            urban_objects_data.join(
                physical_objects_data,
                physical_objects_data.c.physical_object_id == urban_objects_data.c.physical_object_id,
            )
            .join(
                physical_object_types_dict,
                physical_object_types_dict.c.physical_object_type_id == physical_objects_data.c.physical_object_type_id,
            )
            .join(
                object_geometries_data,
                object_geometries_data.c.object_geometry_id == urban_objects_data.c.object_geometry_id,
            )
        )
        .where(
            urban_objects_data.c.urban_object_id.not_in(select(public_urban_object_ids)),
            object_geometries_data.c.object_geometry_id.in_(select(objects_intersecting)),
            physical_object_types_dict.c.physical_object_function_id == physical_object_function_id,
        )
        .subquery()
    )

    await conn.execute(
        insert(projects_urban_objects_data).from_select(
            (
                projects_urban_objects_data.c.scenario_id,
                projects_urban_objects_data.c.public_urban_object_id,
            ),
            select(
                cast(literal(scenario_id), Integer).label("scenario_id"),
                public_urban_objects_query.c.urban_object_id,
            ),
        )
    )

    scenario_urban_objects_query = (
        select(
            projects_urban_objects_data.c.urban_object_id,
            projects_urban_objects_data.c.physical_object_id,
            projects_urban_objects_data.c.object_geometry_id,
            projects_urban_objects_data.c.public_physical_object_id,
        )
        .select_from(
            projects_urban_objects_data.outerjoin(
                projects_physical_objects_data,
                projects_physical_objects_data.c.physical_object_id == projects_urban_objects_data.c.physical_object_id,
            )
            .outerjoin(
                physical_objects_data,
                physical_objects_data.c.physical_object_id == projects_urban_objects_data.c.public_physical_object_id,
            )
            .outerjoin(
                physical_object_types_dict,
                or_(
                    physical_object_types_dict.c.physical_object_type_id
                    == projects_physical_objects_data.c.physical_object_type_id,
                    physical_object_types_dict.c.physical_object_type_id
                    == physical_objects_data.c.physical_object_type_id,
                ),
            )
        )
        .where(
            projects_urban_objects_data.c.scenario_id == scenario_id,
            projects_urban_objects_data.c.public_urban_object_id.is_(None),
            physical_object_types_dict.c.physical_object_function_id == physical_object_function_id,
        )
    )
    result = (await conn.execute(scenario_urban_objects_query)).mappings().all()

    scenario_physical_objects = set(obj.physical_object_id for obj in result if obj.physical_object_id is not None)
    scenario_object_geometries = set(obj.object_geometry_id for obj in result if obj.object_geometry_id is not None)
    scenario_urban_objects = set(obj.urban_object_id for obj in result if obj.public_physical_object_id is not None)

    await conn.execute(
        delete(projects_physical_objects_data).where(
            projects_physical_objects_data.c.physical_object_id.in_(scenario_physical_objects)
        )
    )
    await conn.execute(
        delete(projects_object_geometries_data).where(
            projects_object_geometries_data.c.object_geometry_id.in_(scenario_object_geometries)
        )
    )

    await conn.execute(
        delete(projects_urban_objects_data).where(
            projects_urban_objects_data.c.urban_object_id.in_(scenario_urban_objects)
        )
    )

    statement = (
        insert(projects_physical_objects_data)
        .values(
            [
                {
                    "public_physical_object_id": None,
                    "physical_object_type_id": physical_object.physical_object_type_id,
                    "name": physical_object.name,
                    "properties": physical_object.properties,
                }
                for physical_object in physical_objects
            ]
        )
        .returning(projects_physical_objects_data.c.physical_object_id)
    )
    physical_object_ids = list((await conn.execute(statement)).scalars().all())

    statement = (
        insert(projects_object_geometries_data)
        .values(
            [
                {
                    "public_object_geometry_id": None,
                    "territory_id": physical_object.territory_id,
                    "geometry": ST_GeomFromText(str(physical_object.geometry.as_shapely_geometry()), text("4326")),
                    "centre_point": ST_GeomFromText(
                        str(physical_object.centre_point.as_shapely_geometry()), text("4326")
                    ),
                    "address": physical_object.address,
                    "osm_id": physical_object.osm_id,
                }
                for physical_object in physical_objects
            ]
        )
        .returning(projects_object_geometries_data.c.object_geometry_id)
    )
    object_geometry_ids = list((await conn.execute(statement)).scalars().all())

    statement = (
        insert(projects_urban_objects_data)
        .values(
            [
                {
                    "scenario_id": scenario_id,
                    "physical_object_id": physical_object_ids[i],
                    "object_geometry_id": object_geometry_ids[i],
                }
                for i in range(len(physical_objects))
            ]
        )
        .returning(urban_objects_data.c.urban_object_id)
    )
    urban_object_ids = (await conn.execute(statement)).scalars().all()
    await conn.commit()

    return await get_scenario_urban_object_by_id_from_db(conn, list(urban_object_ids))
