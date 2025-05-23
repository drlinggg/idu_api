"""Service types and urban function schemas are defined here."""

from enum import Enum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from idu_api.urban_api.dto import ServiceTypeDTO, ServiceTypesHierarchyDTO, UrbanFunctionDTO
from idu_api.urban_api.schemas.short_models import UrbanFunctionBasic


class ServiceType(BaseModel):
    service_type_id: int = Field(..., examples=[1])
    urban_function: UrbanFunctionBasic
    name: str = Field(..., description="service type unit name", examples=["Школа"])
    capacity_modeled: int | None = Field(None, description="default capacity", examples=[1])
    code: str = Field(..., description="service type code", examples=["1"])
    infrastructure_type: Literal["basic", "additional", "comfort"] | None = Field(
        ..., description="infrastructure type", examples=["basic"]
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="service type additional properties",
        examples=[{"additional_attribute_name": "additional_attribute_value"}],
    )

    @field_validator("infrastructure_type", mode="before")
    @staticmethod
    def infrastructure_type_to_string(infrastructure_type: Any) -> str:
        if isinstance(infrastructure_type, Enum):
            return infrastructure_type.value
        return infrastructure_type

    @classmethod
    def from_dto(cls, dto: ServiceTypeDTO) -> "ServiceType":
        """
        Construct from DTO.
        """
        return cls(
            service_type_id=dto.service_type_id,
            name=dto.name,
            urban_function=UrbanFunctionBasic(
                id=dto.urban_function_id,
                name=dto.urban_function_name,
            ),
            capacity_modeled=dto.capacity_modeled,
            code=dto.code,
            infrastructure_type=dto.infrastructure_type,
            properties=dto.properties,
        )


class ServiceTypePost(BaseModel):
    urban_function_id: int = Field(..., description="urban function id, if set", examples=[1])
    name: str = Field(..., description="service type unit name", examples=["Школа"])
    capacity_modeled: int | None = Field(None, description="default capacity", examples=[1])
    code: str = Field(..., description="service type code", examples=["1"])
    infrastructure_type: Literal["basic", "additional", "comfort"] | None = Field(
        ..., description="infrastructure type", examples=["basic"]
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="service type additional properties",
        examples=[{"additional_attribute_name": "additional_attribute_value"}],
    )


class ServiceTypePut(BaseModel):
    urban_function_id: int = Field(..., description="urban function id, if set", examples=[1])
    name: str = Field(..., description="service type unit name", examples=["Школа"])
    capacity_modeled: int | None = Field(..., description="default capacity", examples=[1])
    code: str = Field(..., description="service type code", examples=["1"])
    infrastructure_type: Literal["basic", "additional", "comfort"] | None = Field(
        ..., description="infrastructure type", examples=["basic"]
    )
    properties: dict[str, Any] = Field(
        ...,
        description="service type additional properties",
        examples=[{"additional_attribute_name": "additional_attribute_value"}],
    )


class ServiceTypePatch(BaseModel):
    urban_function_id: int | None = Field(None, description="urban function id, if set", examples=[1])
    name: str | None = Field(None, description="service type unit name", examples=["Школа"])
    capacity_modeled: int | None = Field(None, description="default capacity", examples=[1])
    code: str | None = Field(None, description="service type code", examples=["1"])
    infrastructure_type: Literal["basic", "additional", "comfort"] | None = Field(
        None, description="infrastructure type", examples=["basic"]
    )
    properties: dict[str, Any] | None = Field(
        None,
        description="service type additional properties",
        examples=[{"additional_attribute_name": "additional_attribute_value"}],
    )

    @model_validator(mode="before")
    @classmethod
    def check_empty_request(cls, values):
        """Ensure the request body is not empty."""

        if not values:
            raise ValueError("request body cannot be empty")
        return values


class UrbanFunction(BaseModel):
    urban_function_id: int = Field(..., examples=[1])
    parent_urban_function: UrbanFunctionBasic | None
    name: str = Field(..., description="urban function unit name", examples=["Образование"])
    level: int = Field(..., description="number of urban functions above in a tree + [1]", examples=[1])
    list_label: str = Field(..., description="urban function list label", examples=["1.1.1"])
    code: str = Field(..., description="urban function code", examples=["1"])

    @classmethod
    def from_dto(cls, dto: UrbanFunctionDTO) -> "UrbanFunction":
        """
        Construct from DTO.
        """
        return cls(
            urban_function_id=dto.urban_function_id,
            parent_urban_function=(
                UrbanFunctionBasic(
                    id=dto.parent_id,
                    name=dto.parent_urban_function_name,
                )
                if dto.parent_id is not None
                else None
            ),
            name=dto.name,
            level=dto.level,
            list_label=dto.list_label,
            code=dto.code,
        )


class UrbanFunctionPost(BaseModel):
    name: str = Field(..., description="urban function unit name", examples=["Образование"])
    parent_id: int | None = Field(None, description="Urban function parent id, if set", examples=[1])
    code: str = Field(..., description="urban function code", examples=["1"])


class UrbanFunctionPut(BaseModel):
    name: str = Field(..., description="urban function unit name", examples=["Образование"])
    parent_id: int | None = Field(..., description="Urban function parent id, if set", examples=[1])
    code: str = Field(..., description="urban function code", examples=["1"])


class UrbanFunctionPatch(BaseModel):
    name: str | None = Field(None, description="urban function unit name", examples=["Образование"])
    parent_id: int | None = Field(None, description="Urban function parent id, if set", examples=[1])
    code: str | None = Field(None, description="urban function code", examples=["1"])

    @classmethod
    @model_validator(mode="before")
    def check_empty_request(cls, values):
        """Ensure the request body is not empty."""

        if not values:
            raise ValueError("request body cannot be empty")
        return values


class ServiceTypesHierarchy(BaseModel):
    urban_function_id: int = Field(..., examples=[1])
    parent_id: int | None = Field(
        ..., description="parent urban function identifier (null if it is top-level urban function)", examples=[1]
    )
    name: str = Field(..., description="urban function unit name", examples=["Образование"])
    level: int = Field(..., description="number of urban functions above in a tree + [1]", examples=[1])
    list_label: str = Field(..., description="urban function list label", examples=["1.1.1"])
    code: str = Field(..., description="urban function code", examples=["1"])
    children: list[Self | ServiceType]

    @classmethod
    def from_dto(cls, dto: ServiceTypesHierarchyDTO) -> "ServiceTypesHierarchy":
        """
        Construct from DTO.
        """
        return cls(
            urban_function_id=dto.urban_function_id,
            parent_id=dto.parent_id,
            name=dto.name,
            level=dto.level,
            list_label=dto.list_label,
            code=dto.code,
            children=[
                (
                    ServiceTypesHierarchy.from_dto(child)
                    if isinstance(child, ServiceTypesHierarchyDTO)
                    else ServiceType.from_dto(child)
                )
                for child in dto.children
            ],
        )
