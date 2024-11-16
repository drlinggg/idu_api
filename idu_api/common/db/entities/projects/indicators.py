"""Projects indicators values data table is defined here."""

from typing import Callable

from sqlalchemy import TIMESTAMP, Column, Float, ForeignKey, Integer, Sequence, String, Table, func

from idu_api.common.db import metadata
from idu_api.common.db.entities.indicators_dict import indicators_dict
from idu_api.common.db.entities.projects.hexagons_data import hexagons_data
from idu_api.common.db.entities.projects.scenarios import scenarios_data
from idu_api.common.db.entities.territories import territories_data

func: Callable

projects_indicators_data_id_seq = Sequence("projects_indicators_data_id_seq", schema="user_projects")

projects_indicators_data = Table(
    "indicators_data",
    metadata,
    Column(
        "indicator_value_id", Integer, primary_key=True, server_default=projects_indicators_data_id_seq.next_value()
    ),
    Column(
        "scenario_id",
        Integer,
        ForeignKey(scenarios_data.c.scenario_id, ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "indicator_id",
        Integer,
        ForeignKey(indicators_dict.c.indicator_id),
        nullable=False,
    ),
    Column(
        "territory_id",
        Integer,
        ForeignKey(territories_data.c.territory_id),
        nullable=True,
    ),
    Column(
        "hexagon_id",
        Integer,
        ForeignKey(hexagons_data.c.hexagon_id),
        nullable=True,
    ),
    Column("value", Float(53), nullable=False),
    Column("comment", String(2048), nullable=True),
    Column("information_source", String(300), nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", TIMESTAMP(timezone=True), server_default=func.now(), nullable=False),
    schema="user_projects",
)

"""
Indicators data:
- indicator_value_id int
- scenario_id foreign key int
- indicator_id foreign key int
- territory_id foreign key int
- hexagon_id foreign key int
- value float
- comment string(2048)
- information_source string(300)
- created_at timestamp
- updated_at timestamp
"""
