"""
Accuracy evaluation script for email extraction results.
Compares output.json against ground_truth.json.
"""
import json
from typing import Any


def normalize_string(value: Any) -> str:
    """Normalize string for comparison: lowercase, trim whitespace."""
    if value is None:
        return ""
    return str(value).strip().lower()


def normalize_float(value: Any) -> float:
    """Normalize float: round to 2 decimal places."""
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (ValueError, TypeError):
        return None


def fields_match(predicted: Any, ground_truth: Any, field_name: str) -> bool:
    """
    Compare two field values according to evaluation rules:
    - String comparisons: case-insensitive, whitespace trimmed
    - Float comparisons: exact match after rounding to 2 decimal places
    - Null comparisons: null only equals null
    """
    # Handle null values
    if predicted is None and ground_truth is None:
        return True
    if predicted is None or ground_truth is None:
        return False
    
    # Handle numeric fields
    if field_name in ["cargo_weight_kg", "cargo_cbm"]:
        pred_norm = normalize_float(predicted)
        gt_norm = normalize_float(ground_truth)
        return pred_norm == gt_norm
    
    # Handle boolean fields
    if field_name == "is_dangerous":
        return bool(predicted) == bool(ground_truth)
    
    # Handle string fields (case-insensitive, trimmed)
    return normalize_string(predicted) == normalize_string(ground_truth)


def evaluate_single_email(predicted: dict, ground_truth: dict) -> dict:
    """
    Evaluate a single email extraction.
    Returns dict with field-level correctness.
    """
    fields_to_evaluate = [
        "product_line",
        "origin_port_code",
        "origin_port_name",
        "destination_port_code",
        "destination_port_name",
        "incoterm",
        "cargo_weight_kg",
        "cargo_cbm",
        "is_dangerous"
    ]
    
    results = {}
    for field in fields_to_evaluate:
        pred_value = predicted.get(field)
        gt_value = ground_truth.get(field)
        results[field] = fields_match(pred_value, gt_value, field)
    
    return results


def calculate_metrics(predictions: list[dict], ground_truths: list[dict]) -> dict:
    """
    Calculate accuracy metrics across all emails.
    """
    # Create lookup by email ID
    gt_lookup = {gt["id"]: gt for gt in ground_truths}
    
    field_totals = {
        "product_line": 0,
        "origin_port_code": 0,
        "origin_port_name": 0,
        "destination_port_code": 0,
        "destination_port_name": 0,
        "incoterm": 0,
        "cargo_weight_kg": 0,
        "cargo_cbm": 0,
        "is_dangerous": 0
    }
    
    field_correct = field_totals.copy()
    total_fields = 0
    total_correct = 0
    
    email_results = []
    
    for pred in predictions:
        email_id = pred["id"]
        if email_id not in gt_lookup:
            print(f"Warning: {email_id} not found in ground truth")
            continue
        
        gt = gt_lookup[email_id]
        email_eval = evaluate_single_email(pred, gt)
        email_results.append({
            "id": email_id,
            **email_eval
        })
        
        # Aggregate statistics
        for field, is_correct in email_eval.items():
            field_totals[field] += 1
            if is_correct:
                field_correct[field] += 1
                total_correct += 1
            total_fields += 1
    
    # Calculate accuracies
    field_accuracies = {}
    for field in field_totals:
        if field_totals[field] > 0:
            field_accuracies[field] = field_correct[field] / field_totals[field]
        else:
            field_accuracies[field] = 0.0
    
    overall_accuracy = total_correct / total_fields if total_fields > 0 else 0.0
    
    return {
        "overall_accuracy": overall_accuracy,
        "field_accuracies": field_accuracies,
        "field_totals": field_totals,
        "field_correct": field_correct,
        "total_fields": total_fields,
        "total_correct": total_correct,
        "email_results": email_results
    }


def show_mismatches(predictions: list[dict], ground_truths: list[dict], field: str = "destination_port_name", limit: int = 15):
    """Show mismatches for a specific field (useful for debugging)."""
    gt_lookup = {gt["id"]: gt for gt in ground_truths}
    
    mismatches = []
    for pred in predictions:
        email_id = pred["id"]
        if email_id in gt_lookup:
            pred_value = pred.get(field)
            gt_value = gt_lookup[email_id].get(field)
            if pred_value != gt_value:
                mismatches.append((email_id, pred_value, gt_value))
    
    if mismatches:
        print(f"\nFound {len(mismatches)} {field} mismatches:")
        print(f"\nFirst {min(limit, len(mismatches))} mismatches:")
        for email_id, pred, gt in mismatches[:limit]:
            print(f"  {email_id}: got '{pred}', expected '{gt}'")
    else:
        print(f"\nNo mismatches found for {field}!")
    
    return mismatches


def print_metrics(metrics: dict):
    """Print metrics in a readable format."""
    print("=" * 70)
    print("ACCURACY METRICS")
    print("=" * 70)
    print()
    
    print("Field-by-Field Accuracy:")
    print("-" * 70)
    field_names = {
        "product_line": "Product Line",
        "origin_port_code": "Origin Port Code",
        "origin_port_name": "Origin Port Name",
        "destination_port_code": "Destination Port Code",
        "destination_port_name": "Destination Port Name",
        "incoterm": "Incoterm",
        "cargo_weight_kg": "Cargo Weight (kg)",
        "cargo_cbm": "Cargo CBM",
        "is_dangerous": "Is Dangerous"
    }
    
    for field, display_name in field_names.items():
        accuracy = metrics["field_accuracies"][field]
        correct = metrics["field_correct"][field]
        total = metrics["field_totals"][field]
        print(f"{display_name:30s} {accuracy*100:6.2f}% ({correct:3d}/{total:3d})")
    
    print("-" * 70)
    print(f"{'OVERALL ACCURACY':30s} {metrics['overall_accuracy']*100:6.2f}% ({metrics['total_correct']:3d}/{metrics['total_fields']:3d})")
    print("=" * 70)


def show_mismatches(predictions: list[dict], ground_truths: list[dict], field: str = "destination_port_name", limit: int = 15):
    """Show mismatches for a specific field (useful for debugging)."""
    gt_lookup = {gt["id"]: gt for gt in ground_truths}
    
    mismatches = []
    for pred in predictions:
        email_id = pred["id"]
        if email_id in gt_lookup:
            pred_value = pred.get(field)
            gt_value = gt_lookup[email_id].get(field)
            if pred_value != gt_value:
                mismatches.append((email_id, pred_value, gt_value))
    
    if mismatches:
        print(f"\nFound {len(mismatches)} {field} mismatches:")
        print(f"\nFirst {min(limit, len(mismatches))} mismatches:")
        for email_id, pred, gt in mismatches[:limit]:
            print(f"  {email_id}: got '{pred}', expected '{gt}'")
    else:
        print(f"\nNo mismatches found for {field}!")
    
    return mismatches


def main():
    """Main evaluation function."""
    import sys
    
    print("Loading predictions and ground truth...")
    
    # Load predictions
    try:
        with open("output.json", "r", encoding="utf-8") as f:
            predictions = json.load(f)
    except FileNotFoundError:
        print("Error: output.json not found. Please run extract.py first.")
        return
    
    # Load ground truth
    try:
        with open("ground_truth.json", "r", encoding="utf-8") as f:
            ground_truths = json.load(f)
    except FileNotFoundError:
        print("Error: ground_truth.json not found.")
        return
    
    print(f"Evaluating {len(predictions)} predictions against {len(ground_truths)} ground truth entries...")
    print()
    
    # Calculate metrics
    metrics = calculate_metrics(predictions, ground_truths)
    
    # Print results
    print_metrics(metrics)
    
    # Show mismatches if requested via command line argument
    if len(sys.argv) > 1 and sys.argv[1] == "--show-mismatches":
        field = sys.argv[2] if len(sys.argv) > 2 else "destination_port_name"
        show_mismatches(predictions, ground_truths, field)
    
    # Save detailed results
    output_file = "evaluation_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    
    print()
    print(f"Detailed results saved to {output_file}")
    print("\nTip: Run 'python evaluate.py --show-mismatches [field_name]' to see mismatches for a specific field")


if __name__ == "__main__":
    main()

