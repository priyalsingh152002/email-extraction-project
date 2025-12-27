"""
Pydantic models for email extraction output validation.
"""
from typing import Optional
from pydantic import BaseModel, Field


class ShipmentExtraction(BaseModel):
    """Schema for extracted shipment details from email."""
    
    id: str = Field(..., description="Email ID")
    product_line: Optional[str] = Field(None, description="Product line code (pl_sea_import_lcl or pl_sea_export_lcl)")
    origin_port_code: Optional[str] = Field(None, description="UN/LOCODE for origin port (5 letters)")
    origin_port_name: Optional[str] = Field(None, description="Canonical port name from reference")
    destination_port_code: Optional[str] = Field(None, description="UN/LOCODE for destination port (5 letters)")
    destination_port_name: Optional[str] = Field(None, description="Canonical port name from reference")
    incoterm: Optional[str] = Field(None, description="Incoterm (FOB, CIF, CFR, etc.)")
    cargo_weight_kg: Optional[float] = Field(None, description="Cargo weight in kilograms, rounded to 2 decimals")
    cargo_cbm: Optional[float] = Field(None, description="Cargo volume in cubic meters, rounded to 2 decimals")
    is_dangerous: bool = Field(False, description="Whether cargo is dangerous goods")

