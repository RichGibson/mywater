from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

VALID_REPORT_TYPES = {"event", "quality"}
VALID_QUALITY_RATINGS = {"good", "off", "bad"}
VALID_EVENT_SUBTYPES = {"main_break", "outage", "boil_notice", "other"}
FREE_TEXT_MAX_LENGTH = 500


class ReportCreate(BaseModel):
    report_type: str
    obscured: bool
    parcel_id: Optional[int] = None
    cluster_id: Optional[int] = None
    free_text: Optional[str] = None
    taste: Optional[str] = None
    smell: Optional[str] = None
    color: Optional[str] = None
    pressure: Optional[str] = None
    event_subtype: Optional[str] = None
    ongoing: Optional[bool] = None

    @field_validator("report_type")
    @classmethod
    def validate_report_type(cls, v):
        if v not in VALID_REPORT_TYPES:
            raise ValueError(f"report_type must be one of {sorted(VALID_REPORT_TYPES)}")
        return v

    @field_validator("free_text")
    @classmethod
    def validate_free_text_length(cls, v):
        if v is not None and len(v) > FREE_TEXT_MAX_LENGTH:
            raise ValueError(f"free_text must be at most {FREE_TEXT_MAX_LENGTH} characters")
        return v

    @field_validator("taste", "smell", "color", "pressure")
    @classmethod
    def validate_quality_rating(cls, v):
        if v is not None and v not in VALID_QUALITY_RATINGS:
            raise ValueError(f"rating must be one of {sorted(VALID_QUALITY_RATINGS)}")
        return v

    @field_validator("event_subtype")
    @classmethod
    def validate_event_subtype(cls, v):
        if v is not None and v not in VALID_EVENT_SUBTYPES:
            raise ValueError(f"event_subtype must be one of {sorted(VALID_EVENT_SUBTYPES)}")
        return v

    @model_validator(mode="after")
    def validate_location_exclusivity(self):
        if self.obscured:
            if self.cluster_id is None or self.parcel_id is not None:
                raise ValueError("obscured reports must set cluster_id and leave parcel_id unset")
        else:
            if self.parcel_id is None or self.cluster_id is not None:
                raise ValueError("non-obscured reports must set parcel_id and leave cluster_id unset")
        return self

    @model_validator(mode="after")
    def validate_type_specific_fields(self):
        if self.report_type == "event":
            if self.event_subtype is None:
                raise ValueError("event reports require event_subtype")
            if any([self.taste, self.smell, self.color, self.pressure]):
                raise ValueError("event reports must not set quality rating fields")
        elif self.report_type == "quality":
            if self.event_subtype is not None or self.ongoing is not None:
                raise ValueError("quality reports must not set event_subtype or ongoing")
            has_rating = any([self.taste, self.smell, self.color, self.pressure])
            has_text = bool(self.free_text and self.free_text.strip())
            if not has_rating and not has_text:
                raise ValueError("quality reports need at least one rating or free_text")
        return self
