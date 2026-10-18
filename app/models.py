from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Language = Literal["ru", "kk", "en"]
Category = Literal["cafe", "food", "nightlife", "culture", "museum", "landmark",
                   "viewpoint", "park", "family", "activity", "shopping"]


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=50.9, le=51.4, description="Latitude in greater Astana")
    lon: float = Field(ge=71.0, le=71.9, description="Longitude in greater Astana")


class Participant(Location):
    interests: list[Category] = Field(default_factory=list, max_length=6)


class RecommendBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", max_length=500)
    language: Language = "ru"
    time_budget_minutes: int = Field(default=90, ge=20, le=360)
    max_travel_minutes: int | None = Field(default=None, ge=5, le=90)
    starts_at: datetime | None = None
    flight_departure_at: datetime | None = Field(default=None, description="Flight departure with timezone; required if the query gives no time before departure")
    airport_arrival_buffer_minutes: int = Field(default=120, ge=60, le=240, description="Minutes reserved at the airport before departure; check your airline's requirements")
    airport_transfer_mode: Literal["auto", "pedestrian"] = "auto"
    categories: list[Category] = Field(default_factory=list, max_length=11)
    exclude_categories: list[Category] = Field(default_factory=list, max_length=11)
    limit: int = Field(default=3, ge=1, le=3)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_constraints(self):
        if set(self.categories) & set(self.exclude_categories):
            raise ValueError("categories and exclude_categories must not overlap")
        if self.starts_at is not None and self.starts_at.tzinfo is None:
            raise ValueError("starts_at must include a timezone offset")
        if self.flight_departure_at is not None and self.flight_departure_at.tzinfo is None:
            raise ValueError("flight_departure_at must include a timezone offset")
        return self


class RecommendRequest(RecommendBase):
    lat: float | None = Field(default=None, ge=50.9, le=51.4)
    lon: float | None = Field(default=None, ge=71.0, le=71.9)
    reference_place: str | None = Field(default=None, min_length=2, max_length=120,
                                        description="Last named place for phrases such as 'я сейчас там'")
    interests: list[Category] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be provided together")
        return self


class GroupRecommendRequest(RecommendBase):
    participants: list[Participant] = Field(min_length=3, max_length=5)


class PrimaryRecommendRequest(RecommendRequest):
    """Planned recommendations using OSM and nearby 2GIS candidates."""


class TwoGisAttribute(BaseModel):
    name: str
    tag: str | None = None
    id: str | int | None = None


class TwoGisAttributeGroup(BaseModel):
    name: str
    attributes: list[TwoGisAttribute] = Field(default_factory=list)


class PoiOut(BaseModel):
    id: str
    name: str
    category: Category
    lat: float
    lon: float
    description: str | None
    opening_hours: str | None
    website: str | None
    phone: str | None
    source_url: str
    fetched_at: str
    distance_m: int | None = None
    name_is_generic: bool = False
    attribute_groups: list[TwoGisAttributeGroup] = Field(default_factory=list)
    attributes_language: Language | None = None
    rating: float | None = None
    review_count: int | None = None


class Recommendation(BaseModel):
    poi: PoiOut
    distance_m: int
    walking_minutes: int
    walking_seconds: int
    visit_minutes: int
    open_status: Literal["open", "closed", "unknown"]
    open_status_reason: str
    why: str
    what_to_do: str
    text_source: Literal["generated_from_poi"] = "generated_from_poi"
    missing_information: list[str] = Field(default_factory=list)
    airport_transfer_minutes: int | None = None
    airport_transfer_distance_m: int | None = None
    latest_leave_for_airport_at: datetime | None = None
    group_meeting_at: datetime | None = None
    group_ends_at: datetime | None = None
    participant_walking_minutes: list[int] | None = None
    participant_walking_seconds: list[int] | None = None
    participant_interest_matches: list[bool] | None = None


class RecommendResponse(BaseModel):
    recommendations: list[Recommendation]
    language: Language
    context_used: dict
    source: str = "© OpenStreetMap contributors (ODbL), via Overpass API"
    source_license_url: str = "https://www.openstreetmap.org/copyright"
    generated_with: Literal["grounded_templates", "llm_verified"]
    notices: list[str]


class TwoGisNearbyRequest(Location):
    query: str = Field(min_length=2, max_length=500)
    language: Language = "ru"

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("query must contain at least two characters")
        return value


class TwoGisPoi(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    source_url: str | None = None
    object_type: str | None = None
    object_subtype: str | None = None
    address: str | None = None
    description: str | None = None
    rubrics: list[str] = Field(default_factory=list)
    attribute_groups: list[TwoGisAttributeGroup] = Field(default_factory=list)
    attributes_language: Language | None = None
    rating: float | None = None
    review_count: int | None = None
    rating_count: int | None = None
    schedule: dict | None = None
    distance_m: int


class TwoGisNearbyResponse(BaseModel):
    recommendations: list[TwoGisPoi]
    source: Literal["2gis"] = "2gis"
    context_used: dict
    total_found: int | None = None
