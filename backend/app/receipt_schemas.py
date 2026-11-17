from decimal import Decimal
from datetime import datetime
from typing import Annotated, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


ProductCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class ExtractedReceiptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_number: int = Field(ge=1)
    product_code: ProductCode
    quantity: Decimal = Field(gt=0, allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=32)
    unit_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    line_total: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)


class ExtractedReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_number: str | None = Field(default=None, max_length=100)
    purchased_at: datetime | None = None
    currency: CurrencyCode = "PLN"
    subtotal: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    discount_total: Decimal = Field(default=Decimal("0"), ge=0, allow_inf_nan=False)
    total_paid: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    items: list[ExtractedReceiptItem] = Field(min_length=1)


class ResolveProductCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_type: Literal["accepted_as_is", "edited_code", "mapped_existing"]
    product_code: ProductCode | None = None
    product_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_resolution_fields(self) -> "ResolveProductCandidateRequest":
        if self.resolution_type == "edited_code":
            if self.product_code is None or self.product_id is not None:
                raise ValueError("Edited-code resolution requires only product_code")
        elif self.resolution_type == "mapped_existing":
            if self.product_id is None or self.product_code is not None:
                raise ValueError("Mapped resolution requires only product_id")
        elif self.product_code is not None or self.product_id is not None:
            raise ValueError("Accept-as-is resolution does not accept extra values")
        return self
