"""Functional zones handlers logic of getting entities from the database is defined here."""

import abc
from typing import Protocol

from idu_api.urban_api.dto import FunctionalZoneTypeDTO, ProfilesReclamationDataDTO, ProfilesReclamationDataMatrixDTO
from idu_api.urban_api.schemas import FunctionalZoneTypePost, ProfilesReclamationDataPost, ProfilesReclamationDataPut


class FunctionalZonesService(Protocol):
    """Service to manipulate functional zone objects."""

    @abc.abstractmethod
    async def get_functional_zone_types(self) -> list[FunctionalZoneTypeDTO]:
        """Get all functional zone type objects."""

    @abc.abstractmethod
    async def add_functional_zone_type(self, functional_zone_type: FunctionalZoneTypePost) -> FunctionalZoneTypeDTO:
        """Create functional zone type object."""

    @abc.abstractmethod
    async def get_profiles_reclamation_data(self) -> list[ProfilesReclamationDataDTO]:
        """Get a list of profiles reclamation data."""

    @abc.abstractmethod
    async def get_all_sources(self) -> list[int]:
        """Get a list of all profiles reclamation sources."""

    @abc.abstractmethod
    async def get_profiles_reclamation_data_matrix(self, labels: list[int]) -> ProfilesReclamationDataMatrixDTO:
        """Get a matrix of profiles reclamation data for specific labels."""

    @abc.abstractmethod
    async def add_profiles_reclamation_data(
        self, profiles_reclamation: ProfilesReclamationDataPost
    ) -> ProfilesReclamationDataDTO:
        """Add a new profiles reclamation data."""

    @abc.abstractmethod
    async def put_profiles_reclamation_data(
        self, profiles_reclamation: ProfilesReclamationDataPut
    ) -> ProfilesReclamationDataDTO:
        """Put profiles reclamation data."""
