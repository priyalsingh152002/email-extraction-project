# Email Extraction System for Freight Forwarding

LLM-powered email extraction system for processing freight forwarding pricing enquiries. Extracts structured shipment details from unstructured emails using Groq's Llama models.

## Setup

### Prerequisites
- Python 3.8+
- Groq API account (free tier available at https://console.groq.com)

### Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up Groq API key:**
   - Sign up at https://console.groq.com (free, no credit card required)
   - Create an API key from the dashboard
   - Create a `.env` file in the project root:
     ```
     GROQ_API_KEY=your_groq_api_key_here
     ```

3. **Run extraction:**
   ```bash
   python extract.py      # Generates output.json
   ```
   - Processing 50 emails takes approximately 5-10 minutes due to rate limits
   - The script handles interruptions gracefully (Ctrl+C) and saves progress

4. **Evaluate accuracy:**
   ```bash
   python evaluate.py     # Shows accuracy metrics
   python evaluate.py --show-mismatches destination_port_name  # Debug specific fields
   ```

5. **Optional utilities:**
   ```bash
   python extract.py --fix-port-names  # Fix port names in existing output.json
   ```

## Accuracy Results

Final accuracy: **91.56%** overall (412/450 fields)

```
Field-by-Field Accuracy:
----------------------------------------------------------------------
Product Line                   100.00% ( 50/ 50)
Origin Port Code               100.00% ( 50/ 50)
Origin Port Name                90.00% ( 45/ 50)
Destination Port Code           96.00% ( 48/ 50)
Destination Port Name           64.00% ( 32/ 50)
Incoterm                        96.00% ( 48/ 50)
Cargo Weight (kg)               82.00% ( 41/ 50)
Cargo CBM                       96.00% ( 48/ 50)
Is Dangerous                   100.00% ( 50/ 50)
----------------------------------------------------------------------
OVERALL ACCURACY                91.56% (412/450)
```

**Analysis:**
- **Perfect fields (100%)**: Product Line, Origin Port Code, Is Dangerous
- **High accuracy (90%+)**: Origin Port Name, Destination Port Code, Incoterm, Cargo CBM
- **Moderate accuracy (80-90%)**: Cargo Weight (kg) - unit conversion edge cases
- **Lower accuracy (64%)**: Destination Port Name - strict canonical name matching

**Improvement Journey:**
- v1: ~62% (basic extraction)
- v2: ~78% (added UN/LOCODE examples)
- v3: ~85% (comprehensive business rules)
- Final: **91.56%** (v3 + post-processing improvements)

Port name fields remain lower than codes due to strict string matching against canonical names; in production, port names are always derived from the resolved UN/LOCODE to eliminate alias ambiguity.

## Prompt Evolution

The prompt went through three iterations. All versions are available in `prompts.py`:

- **v1**: Basic extraction (~62% accuracy)
  - Simple prompt with minimal instructions
  - Issues: Port codes returned as city names, missing incoterms defaulted incorrectly

- **v2**: Added UN/LOCODE examples (~78% accuracy)
  - Included full port codes reference
  - Explicit UN/LOCODE format requirements (5 letters: 2-letter country + 3-letter location)
  - Issues: India detection logic failed for ports with multiple name variations

- **v3**: Comprehensive business rules (current, ~85% before post-processing)
  - Conflict resolution (body takes precedence over subject)
  - Unit conversion instructions (lbs × 0.453592, tonnes × 1000)
  - Dangerous goods negation handling ("non-DG" → false)
  - Multiple shipment handling (extract first shipment only)
  - Numeric field validation (TBD/N/A → null)
  - Comprehensive port code matching

## Edge Cases Handled

1. **Port Name Variations**: Canonical name selection algorithm prefers shorter names without "ICD" suffix
2. **Subject vs Body Conflicts**: Body takes precedence (more detailed context)
3. **Multiple Shipments**: Extract first shipment only
4. **Unit Conversions**: Handles lbs, tonnes, MT, tons with proper conversion factors
5. **Dangerous Goods Negations**: Handles "non-DG", "non-hazardous", "not dangerous" patterns
6. **TBD/N/A Values**: Maps to null for weight/CBM fields

## System Design

### Scale: 10,000 emails/day, 99% processed within 5 minutes, $500/month budget

**Architecture:**
- **Message Queue**: RabbitMQ or AWS SQS to buffer emails and handle spikes
- **Worker Pool**: 10-20 worker processes (auto-scaling based on queue depth)
- **API Optimization**: Batch processing, use cheaper models for simple cases, cache port code lookups
- **Cost Management**: ~$105/month for Groq API, remaining budget for infrastructure
- **Latency**: With 20 workers, 99% complete within 5 minutes of arrival

**Trade-offs**: Prioritize cost-efficiency over perfect accuracy by using smaller models for simple cases.

### Monitoring: Accuracy drops from 90% to 70% over a week

**Detection:**
- Real-time monitoring with time-series DB (Prometheus/InfluxDB)
- Alerts on accuracy drop >5% in 24h, field-level accuracy <80%, spike in null values

**Investigation:**
- Root cause analysis: Check specific field degradation, analyze failed emails for patterns, compare distribution shifts
- Data analysis: Sample 50-100 recent failures, check for new port codes, verify business rules
- Remediation: Update prompt/examples, update reference files, test different model versions

**Prevention:**
- Weekly accuracy reports with trend analysis
- A/B testing for prompt changes
- Human-in-the-loop review of low-confidence extractions

### Multilingual: 30% emails in Mandarin, 20% in Hindi

**Changes Required:**
1. **LLM Selection**: Use multilingual models (llama-3.1-70b supports 100+ languages)
2. **Prompt Adaptation**: Translate prompt, include examples in all three languages
3. **Port Code Reference**: Add multilingual aliases to reference file
4. **Evaluation Strategy**: Separate accuracy metrics per language, field-level analysis
5. **Challenges**: Port name transliterations, incoterm abbreviations, number formats

**Trade-off**: Multilingual support may slightly reduce English accuracy due to prompt complexity.

## Rate Limit Handling

The system detects rate-limit errors and gracefully retries with exponential backoff. If the limit persists, the pipeline records the email with null fields instead of crashing, ensuring deterministic output.

**Implementation:**
- Retry logic: 3 retries with exponential backoff (1s, 2s, 4s)
- Error handling: Distinguishes between per-minute rate limits (retry) and daily token limits (stop gracefully)
- Graceful degradation: Failed extractions included in output.json with null values
- Interruption handling: KeyboardInterrupt (Ctrl+C) saves partial progress before exiting

## Project Structure

```
th-backend-assessment/
├── README.md                   # This file
├── requirements.txt            # Python dependencies
├── .env                        # API keys (not in git)
├── .env.example                # API key template
├── schemas.py                  # Pydantic models for validation
├── prompts.py                  # Prompt templates (v1, v2, v3)
├── extract.py                  # Main extraction script
├── evaluate.py                 # Accuracy calculator
├── emails_input.json           # 50 sample emails
├── ground_truth.json           # Expected outputs
├── port_codes_reference.json   # UN/LOCODE mappings
├── output.json                 # Generated extraction results
└── evaluation_results.json    # Detailed evaluation metrics
```

## Key Features

1. **Robust Error Handling**: Failed extractions included with null values rather than skipped
2. **Port Code Normalization**: Matches port names to UN/LOCODE using reference file
3. **Business Rule Enforcement**: Post-processing ensures compliance with all business rules
4. **Reproducibility**: Temperature=0 for consistent results
5. **Rate Limit Management**: Exponential backoff and delays to handle Groq free tier limits
6. **Graceful Interruption**: Ctrl+C saves progress before exiting

