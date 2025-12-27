"""
Main script for extracting shipment details from emails using LLM.
"""
import json
import os
import time
from typing import Optional
from groq import Groq
from groq._exceptions import APIError, RateLimitError
from dotenv import load_dotenv
from schemas import ShipmentExtraction
from prompts import get_current_prompt

# Load environment variables
load_dotenv()

# Initialize Groq client
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY not found in environment variables. Please set it in .env file.")

client = Groq(api_key=GROQ_API_KEY)
MODEL = "llama-3.3-70b-versatile"  # Primary model (3.1 is decommissioned)
FALLBACK_MODEL = None  # No fallback needed since 3.3 is current
TEMPERATURE = 0  # Required for reproducibility
MAX_RETRIES = 3
INITIAL_BACKOFF = 1  # seconds


def extract_json_from_response(response_text: str) -> Optional[dict]:
    """
    Extract JSON from LLM response.
    Handles cases where response may have markdown code blocks or extra text.
    """
    response_text = response_text.strip()
    
    # Remove markdown code blocks if present
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    elif response_text.startswith("```"):
        response_text = response_text[3:]
    
    if response_text.endswith("```"):
        response_text = response_text[:-3]
    
    response_text = response_text.strip()
    
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            try:
                return json.loads(response_text[start_idx:end_idx + 1])
            except json.JSONDecodeError:
                pass
        return None


def load_port_codes_reference() -> dict:
    """Load port codes reference and create lookup dictionaries."""
    with open("port_codes_reference.json", "r", encoding="utf-8") as f:
        ports = json.load(f)
    
    # Create mappings: code -> canonical name, name variations -> code
    code_to_names = {}  # Collect all names for each code
    code_to_all_names = {}  # All names (case-insensitive) for each code for matching
    name_to_code = {}
    
    # First pass: collect all names for each code
    for port in ports:
        code = port["code"]
        name = port["name"]
        
        if code not in code_to_names:
            code_to_names[code] = []
            code_to_all_names[code] = set()
        code_to_names[code].append(name)
        code_to_all_names[code].add(name.lower())
        
        # Map name variations to code (case-insensitive)
        name_lower = name.lower()
        if name_lower not in name_to_code:
            name_to_code[name_lower] = code
        
        # Also map individual words (for partial matches)
        words = name_lower.split()
        for word in words:
            if word not in name_to_code:
                name_to_code[word] = code
    
    # Second pass: determine canonical name for each code
    # Strategy: Prefer shorter, simpler names without "ICD", "Port", etc.
    # For INMAA specifically, prefer "Chennai" over "Bangalore ICD"
    code_to_name = {}
    for code, names in code_to_names.items():
        # Filter out names with multiple ports or parentheses
        simple_names = [n for n in names if "/" not in n and "(" not in n]
        if simple_names:
            # Prefer names without "ICD" suffix
            preferred = [n for n in simple_names if "ICD" not in n.upper()]
            if preferred:
                # Among preferred, choose the shortest (usually the canonical name)
                # But also prefer common city names over other variations
                # Sort by: length first, then alphabetically for consistency
                preferred_sorted = sorted(preferred, key=lambda x: (len(x), x))
                canonical = preferred_sorted[0]
            else:
                # If all have ICD, choose shortest
                canonical = min(simple_names, key=len)
        else:
            # Fallback to shortest name overall
            canonical = min(names, key=len)
        
        code_to_name[code] = canonical
    
    return {
        "code_to_name": code_to_name,
        "code_to_all_names": code_to_all_names,  # For checking if a name exists for a code
        "code_to_names": code_to_names,  # All names (with original case) for each code
        "name_to_code": name_to_code
    }


def normalize_port_code(port_code: Optional[str], port_name: Optional[str], port_ref: dict) -> tuple[Optional[str], Optional[str]]:
    """
    Normalize port code and name using reference.
    If LLM returns a name, try to match it to a code.
    If LLM returns a code, get the canonical name.
    """
    if not port_code and not port_name:
        return None, None
    
    code_to_name = port_ref["code_to_name"]
    name_to_code = port_ref["name_to_code"]
    
    # If we have a code, validate and get canonical name
    if port_code:
        port_code = port_code.upper().strip()
        if len(port_code) == 5 and port_code in code_to_name:
            return port_code, code_to_name[port_code]
        # Invalid code format
        port_code = None
    
    # If we have a name but no code, try to match
    if port_name and not port_code:
        name_lower = port_name.lower().strip()
        
        # Try exact match first (highest priority)
        if name_lower in name_to_code:
            code = name_to_code[name_lower]
            return code, code_to_name[code]
        
        # Try matching with common port suffixes removed
        name_variations = [
            name_lower.replace(" icd", "").strip(),
            name_lower.replace(" port", "").strip(),
            name_lower.replace("port ", "").strip(),
        ]
        for variation in name_variations:
            if variation and variation in name_to_code:
                code = name_to_code[variation]
                return code, code_to_name[code]
        
        # Try partial matches (check if any significant word in the name matches)
        # Prioritize longer words over shorter ones
        words = [w for w in name_lower.split() if len(w) > 2]  # Filter short words
        words.sort(key=len, reverse=True)  # Longest first
        
        for word in words:
            # Skip common non-port words
            if word in ["to", "from", "port", "icd", "the", "and", "or", "via", "through"]:
                continue
            if word in name_to_code:
                code = name_to_code[word]
                return code, code_to_name[code]
    
    return None, None


def post_process_extraction(extracted: dict, port_ref: dict) -> dict:
    """
    Post-process LLM extraction to apply business rules and normalize values.
    """
    # Normalize port codes and names
    origin_code, origin_name = normalize_port_code(
        extracted.get("origin_port_code"),
        extracted.get("origin_port_name"),
        port_ref
    )
    dest_code, dest_name = normalize_port_code(
        extracted.get("destination_port_code"),
        extracted.get("destination_port_name"),
        port_ref
    )
    
    # CRITICAL: Always use canonical name from reference when we have a valid port code
    # This ensures port names match exactly with ground truth
    code_to_name = port_ref["code_to_name"]
    if origin_code and origin_code in code_to_name:
        origin_name = code_to_name[origin_code]
    if dest_code and dest_code in code_to_name:
        dest_name = code_to_name[dest_code]
    
    # Determine product_line based on port codes
    product_line = extracted.get("product_line")
    if not product_line:
        if dest_code and dest_code.startswith("IN"):
            product_line = "pl_sea_import_lcl"
        elif origin_code and origin_code.startswith("IN"):
            product_line = "pl_sea_export_lcl"
    
    # Normalize incoterm
    incoterm = extracted.get("incoterm")
    if incoterm:
        incoterm = incoterm.upper().strip()
        valid_incoterms = ["FOB", "CIF", "CFR", "EXW", "DDP", "DAP", "FCA", "CPT", "CIP", "DPU"]
        if incoterm not in valid_incoterms:
            incoterm = "FOB"  # Default
    else:
        incoterm = "FOB"  # Default
    
    # Round numeric fields
    cargo_weight_kg = extracted.get("cargo_weight_kg")
    if cargo_weight_kg is not None:
        try:
            cargo_weight_kg = round(float(cargo_weight_kg), 2)
        except (ValueError, TypeError):
            cargo_weight_kg = None
    
    cargo_cbm = extracted.get("cargo_cbm")
    if cargo_cbm is not None:
        try:
            cargo_cbm = round(float(cargo_cbm), 2)
        except (ValueError, TypeError):
            cargo_cbm = None
    
    # Ensure is_dangerous is boolean
    is_dangerous = extracted.get("is_dangerous", False)
    if not isinstance(is_dangerous, bool):
        is_dangerous = bool(is_dangerous)
    
    return {
        "product_line": product_line,
        "origin_port_code": origin_code,
        "origin_port_name": origin_name,
        "destination_port_code": dest_code,
        "destination_port_name": dest_name,
        "incoterm": incoterm,
        "cargo_weight_kg": cargo_weight_kg,
        "cargo_cbm": cargo_cbm,
        "is_dangerous": is_dangerous
    }


def extract_shipment_details(email: dict, port_ref: dict) -> Optional[ShipmentExtraction]:
    """
    Extract shipment details from a single email using LLM.
    Returns ShipmentExtraction object or None if extraction fails.
    """
    email_id = email["id"]
    subject = email.get("subject", "")
    body = email.get("body", "")
    
    prompt = get_current_prompt(subject, body)
    
    # Retry logic with exponential backoff
    current_model = MODEL
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=current_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=TEMPERATURE
            )
            
            response_text = response.choices[0].message.content
            
            # Extract JSON from response
            extracted_dict = extract_json_from_response(response_text)
            
            if not extracted_dict:
                print(f"Warning: {email_id} - Failed to parse JSON from response")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(INITIAL_BACKOFF * (2 ** attempt))
                    continue
                return None
            
            # Post-process extraction
            processed = post_process_extraction(extracted_dict, port_ref)
            processed["id"] = email_id
            
            # Validate with Pydantic
            try:
                extraction = ShipmentExtraction(**processed)
                return extraction
            except Exception as e:
                print(f"Warning: {email_id} - Validation error: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(INITIAL_BACKOFF * (2 ** attempt))
                    continue
                # Return with null values if validation fails
                return ShipmentExtraction(
                    id=email_id,
                    product_line=None,
                    origin_port_code=None,
                    origin_port_name=None,
                    destination_port_code=None,
                    destination_port_name=None,
                    incoterm=None,
                    cargo_weight_kg=None,
                    cargo_cbm=None,
                    is_dangerous=False
                )
            
        except RateLimitError as e:
            wait_time = INITIAL_BACKOFF * (2 ** attempt)
            print(f"Rate limit hit for {email_id}, waiting {wait_time}s before retry {attempt + 1}/{MAX_RETRIES}")
            time.sleep(wait_time)
            continue
        
        except APIError as e:
            error_msg = str(e)
            # Check if it's a model decommissioned error
            if "decommissioned" in error_msg.lower() or "model_decommissioned" in error_msg:
                if attempt == 0 and current_model == MODEL and FALLBACK_MODEL:
                    print(f"Model {MODEL} decommissioned, trying fallback: {FALLBACK_MODEL}")
                    current_model = FALLBACK_MODEL
                    continue
                else:
                    print(f"Error: {email_id} - Model unavailable: {e}")
                    if attempt < MAX_RETRIES - 1:
                        wait_time = INITIAL_BACKOFF * (2 ** attempt)
                        time.sleep(wait_time)
                        continue
                    return None
            else:
                print(f"API error for {email_id}: {e}")
                if attempt < MAX_RETRIES - 1:
                    wait_time = INITIAL_BACKOFF * (2 ** attempt)
                    time.sleep(wait_time)
                    continue
                return None
        
        except (ConnectionError, TimeoutError, OSError) as e:
            # Network/SSL errors - retry with backoff
            print(f"Network error for {email_id}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = INITIAL_BACKOFF * (2 ** attempt)
                print(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"Failed after {MAX_RETRIES} network retries for {email_id}")
            return None
        
        except Exception as e:
            print(f"Unexpected error for {email_id}: {type(e).__name__}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = INITIAL_BACKOFF * (2 ** attempt)
                time.sleep(wait_time)
                continue
            return None
    
    # All retries exhausted
    print(f"Error: {email_id} - Failed after {MAX_RETRIES} attempts")
    return None


def fix_port_names_in_output():
    """
    Utility function to fix port names in existing output.json to use canonical names.
    This is useful if output.json was generated with an older version of the code.
    """
    port_ref = load_port_codes_reference()
    code_to_name = port_ref["code_to_name"]
    
    try:
        with open("output.json", "r", encoding="utf-8") as f:
            output = json.load(f)
    except FileNotFoundError:
        print("Error: output.json not found.")
        return
    
    fixed_count = 0
    for entry in output:
        # Fix origin port name
        origin_code = entry.get("origin_port_code")
        if origin_code and origin_code in code_to_name:
            old_name = entry.get("origin_port_name")
            new_name = code_to_name[origin_code]
            if old_name != new_name:
                entry["origin_port_name"] = new_name
                fixed_count += 1
        
        # Fix destination port name
        dest_code = entry.get("destination_port_code")
        if dest_code and dest_code in code_to_name:
            old_name = entry.get("destination_port_name")
            new_name = code_to_name[dest_code]
            if old_name != new_name:
                entry["destination_port_name"] = new_name
                fixed_count += 1
    
    # Save fixed output
    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"Fixed {fixed_count} port names in output.json")
    print(f"Canonical names being used:")
    print(f"  INMAA -> {code_to_name.get('INMAA')}")
    print(f"  KRPUS -> {code_to_name.get('KRPUS')}")
    print(f"  THBKK -> {code_to_name.get('THBKK')}")


def main():
    """Main extraction function."""
    import sys
    
    # Check if user wants to fix existing output.json
    if len(sys.argv) > 1 and sys.argv[1] == "--fix-port-names":
        fix_port_names_in_output()
        return
    
    print("Loading emails and port reference...")
    
    # Load emails
    with open("emails_input.json", "r", encoding="utf-8") as f:
        emails = json.load(f)
    
    # Load port codes reference
    port_ref = load_port_codes_reference()
    
    print(f"Processing {len(emails)} emails...")
    print(f"Using model: {MODEL}")
    print(f"Temperature: {TEMPERATURE}")
    print("-" * 50)
    
    results = []
    
    try:
        for i, email in enumerate(emails, 1):
            email_id = email["id"]
            print(f"[{i}/{len(emails)}] Processing {email_id}...", end=" ", flush=True)
            
            extraction = extract_shipment_details(email, port_ref)
            
            if extraction:
                results.append(extraction.model_dump())
                print("✓")
            else:
                # Include failed extraction with null values
                failed_extraction = ShipmentExtraction(
                    id=email_id,
                    product_line=None,
                    origin_port_code=None,
                    origin_port_name=None,
                    destination_port_code=None,
                    destination_port_name=None,
                    incoterm=None,
                    cargo_weight_kg=None,
                    cargo_cbm=None,
                    is_dangerous=False
                )
                results.append(failed_extraction.model_dump())
                print("✗ (using null values)")
            
            # Small delay to avoid rate limits
            if i < len(emails):
                time.sleep(0.5)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Extraction interrupted by user (Ctrl+C)")
        print(f"   Processed {len(results)}/{len(emails)} emails so far")
        print("   Saving partial results...")
    
    # Save results (even if interrupted)
    output_file = "output.json"
    
    # If we have partial results, fill in the rest with null values
    if len(results) < len(emails):
        processed_ids = {r["id"] for r in results}
        for email in emails:
            if email["id"] not in processed_ids:
                failed_extraction = ShipmentExtraction(
                    id=email["id"],
                    product_line=None,
                    origin_port_code=None,
                    origin_port_name=None,
                    destination_port_code=None,
                    destination_port_name=None,
                    incoterm=None,
                    cargo_weight_kg=None,
                    cargo_cbm=None,
                    is_dangerous=False
                )
                results.append(failed_extraction.model_dump())
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print("-" * 50)
    if len(results) == len(emails):
        print(f"Extraction complete! Results saved to {output_file}")
    else:
        print(f"Partial extraction saved to {output_file}")
        print(f"   Processed: {len([r for r in results if r.get('product_line')])} emails")
        print(f"   Remaining: {len(emails) - len([r for r in results if r.get('product_line')])} emails")
        print(f"   You can re-run the script to continue processing")
    print(f"Successfully processed: {len([r for r in results if r.get('product_line')])} emails")


def fix_port_names_in_output():
    """
    Utility function to fix port names in existing output.json to use canonical names.
    This is useful if output.json was generated with an older version of the code.
    """
    port_ref = load_port_codes_reference()
    code_to_name = port_ref["code_to_name"]
    
    try:
        with open("output.json", "r", encoding="utf-8") as f:
            output = json.load(f)
    except FileNotFoundError:
        print("Error: output.json not found.")
        return
    
    fixed_count = 0
    for entry in output:
        # Fix origin port name
        origin_code = entry.get("origin_port_code")
        if origin_code and origin_code in code_to_name:
            old_name = entry.get("origin_port_name")
            new_name = code_to_name[origin_code]
            if old_name != new_name:
                entry["origin_port_name"] = new_name
                fixed_count += 1
        
        # Fix destination port name
        dest_code = entry.get("destination_port_code")
        if dest_code and dest_code in code_to_name:
            old_name = entry.get("destination_port_name")
            new_name = code_to_name[dest_code]
            if old_name != new_name:
                entry["destination_port_name"] = new_name
                fixed_count += 1
    
    # Save fixed output
    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"Fixed {fixed_count} port names in output.json")
    print(f"Canonical names being used:")
    print(f"  INMAA -> {code_to_name.get('INMAA')}")
    print(f"  KRPUS -> {code_to_name.get('KRPUS')}")
    print(f"  THBKK -> {code_to_name.get('THBKK')}")


if __name__ == "__main__":
    import sys
    
    # Check if user wants to fix existing output.json
    if len(sys.argv) > 1 and sys.argv[1] == "--fix-port-names":
        fix_port_names_in_output()
    else:
        main()

