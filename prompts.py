"""
Prompt templates for LLM-based email extraction.
Shows evolution from v1 to v3 with improvements.
"""
import json


def load_port_codes_reference() -> list:
    """Load port codes reference file."""
    with open("port_codes_reference.json", "r", encoding="utf-8") as f:
        return json.load(f)


def get_port_codes_context() -> str:
    """Generate context string with port codes for the prompt."""
    ports = load_port_codes_reference()
    
    # Group by code to show variations
    port_dict = {}
    for port in ports:
        code = port["code"]
        if code not in port_dict:
            port_dict[code] = []
        port_dict[code].append(port["name"])
    
    # Format for prompt
    lines = []
    for code, names in sorted(port_dict.items()):
        unique_names = list(set(names))
        lines.append(f"- {code}: {', '.join(unique_names)}")
    
    return "\n".join(lines)


# Valid incoterms
VALID_INCOTERMS = ["FOB", "CIF", "CFR", "EXW", "DDP", "DAP", "FCA", "CPT", "CIP", "DPU"]


def get_prompt_v1(subject: str, body: str) -> str:
    """
    Version 1: Basic extraction prompt.
    Initial attempt with minimal instructions.
    """
    return f"""Extract shipment details from this email:

Subject: {subject}
Body: {body}

Extract the following information:
- Origin port (city/country name)
- Destination port (city/country name)
- Incoterm (FOB, CIF, etc.)
- Cargo weight in kg
- Cargo volume in CBM
- Whether cargo is dangerous goods

Return as JSON with keys: origin_port, destination_port, incoterm, cargo_weight_kg, cargo_cbm, is_dangerous."""


def get_prompt_v2(subject: str, body: str) -> str:
    """
    Version 2: Added UN/LOCODE examples and port reference.
    Improved port code matching with reference list.
    """
    port_context = get_port_codes_context()
    
    return f"""Extract shipment details from this freight forwarding email.

Email:
Subject: {subject}
Body: {body}

Port Codes Reference (UN/LOCODE format - 5 letters: 2-letter country + 3-letter location):
{port_context}

Instructions:
1. Identify origin and destination ports. Match them to UN/LOCODE format (5 letters).
2. Determine product_line: If destination starts with "IN" (India) → "pl_sea_import_lcl", if origin starts with "IN" → "pl_sea_export_lcl"
3. Extract incoterm (FOB, CIF, CFR, EXW, DDP, DAP, FCA, CPT, CIP, DPU). Default to FOB if not mentioned.
4. Extract cargo_weight_kg (convert lbs to kg: multiply by 0.453592, tonnes to kg: multiply by 1000)
5. Extract cargo_cbm (cubic meters)
6. Determine is_dangerous: true if mentions "DG", "dangerous", "hazardous", "Class" + number, "IMO", "IMDG". False if mentions "non-DG", "non-hazardous", "not dangerous", "non hazardous". Default false.

Return JSON:
{{
  "product_line": "pl_sea_import_lcl" or "pl_sea_export_lcl",
  "origin_port_code": "UN/LOCODE (5 letters) or null",
  "origin_port_name": "canonical name from reference or null",
  "destination_port_code": "UN/LOCODE (5 letters) or null",
  "destination_port_name": "canonical name from reference or null",
  "incoterm": "FOB/CIF/etc or null",
  "cargo_weight_kg": number or null,
  "cargo_cbm": number or null,
  "is_dangerous": true or false
}}"""


def get_prompt_v3(subject: str, body: str) -> str:
    """
    Version 3: Final version with comprehensive business rules.
    Includes conflict resolution, unit conversions, and edge case handling.
    """
    port_context = get_port_codes_context()
    
    return f"""You are an expert at extracting structured shipment details from freight forwarding emails.

Email:
Subject: {subject}
Body: {body}

PORT CODES REFERENCE (UN/LOCODE - 5 letters: 2-letter country + 3-letter location):
{port_context}

BUSINESS RULES:

1. PRODUCT LINE:
   - If destination port code starts with "IN" (India) → "pl_sea_import_lcl"
   - If origin port code starts with "IN" (India) → "pl_sea_export_lcl"
   - All shipments in this assessment are LCL

2. PORT CODES:
   - Must be UN/LOCODE format (5 letters: 2-letter country + 3-letter location)
   - Match port names from email to reference list above
   - Use canonical port name from reference for the matched code
   - If port not found in reference → use null for code and name
   - Common abbreviations: "HK" = Hong Kong (HKHKG), "Mumbai" = Nhava Sheva (INNSA)

3. CONFLICT RESOLUTION:
   - Body takes precedence over Subject when there's a conflict
   - If multiple shipments mentioned → extract the FIRST one only
   - If multiple ports mentioned → use origin→destination pair, ignore intermediate/transshipment ports

4. INCOTERMS:
   - Valid: FOB, CIF, CFR, EXW, DDP, DAP, FCA, CPT, CIP, DPU
   - Normalize to uppercase
   - If not mentioned or ambiguous → default to "FOB"
   - If email says "FOB or CIF" → default to "FOB"

5. NUMERIC FIELDS:
   - Round cargo_weight_kg and cargo_cbm to 2 decimal places
   - Convert lbs to kg: multiply by 0.453592
   - Convert tonnes/MT to kg: multiply by 1000
   - "TBD", "N/A", "to be confirmed" → null
   - Explicit zero (e.g., "0 kg") → 0, not null
   - If dimensions (L×W×H) given → do NOT calculate CBM, use null
   - Extract both weight AND CBM if both mentioned

6. DANGEROUS GOODS:
   - is_dangerous = true if contains: "DG", "dangerous", "hazardous", "Class" + number (e.g., "Class 3"), "IMO", "IMDG"
   - is_dangerous = false if contains: "non-hazardous", "non-DG", "not dangerous", "non hazardous" (with or without hyphen)
   - Default: false

OUTPUT FORMAT (JSON only, no markdown):
{{
  "product_line": "pl_sea_import_lcl" or "pl_sea_export_lcl" or null,
  "origin_port_code": "5-letter UN/LOCODE or null",
  "origin_port_name": "canonical name from reference or null",
  "destination_port_code": "5-letter UN/LOCODE or null",
  "destination_port_name": "canonical name from reference or null",
  "incoterm": "FOB/CIF/CFR/EXW/DDP/DAP/FCA/CPT/CIP/DPU or null",
  "cargo_weight_kg": number (rounded to 2 decimals) or null,
  "cargo_cbm": number (rounded to 2 decimals) or null,
  "is_dangerous": true or false
}}

Return ONLY valid JSON, no additional text."""


def get_current_prompt(subject: str, body: str) -> str:
    """Get the current production prompt (v3)."""
    return get_prompt_v3(subject, body)

