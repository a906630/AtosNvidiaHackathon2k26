# Crisis Management API Examples

This directory contains realistic incident examples for testing and demonstration of the Crisis Management Center (CZK) API.

## Structure

```
examples/
├── send_incidents.py       # Script to send all incidents to the API
├── incidents/
│   ├── flood_*.json        # 10 flood incident examples
│   ├── cyber_*.json        # 10 cyber attack incident examples
│   ├── terror_*.json       # 10 terror attack incident examples
│   ├── infrastructure_*.json # 10 infrastructure failure examples
│   └── traffic_*.json      # 10 traffic incident examples
└── README.md               # This file
```

## Incident Categories

### Flood (10 examples)
Real-world scenarios from Polish regions:
- River overflows (Odra, Vistula, Warta)
- Street flooding from heavy rainfall
- Storm surge alerts
- Dam and levee breaches
- Mine flooding
- Infrastructure water damage

### Cyber (10 examples)
Security incidents affecting various sectors:
- Ransomware attacks on government
- DDoS attacks on financial institutions
- Phishing campaigns
- Supply chain compromises
- Zero-day exploits
- APT group activity
- Botnet infections
- MITM attacks
- Data exfiltration
- Legacy system vulnerabilities

### Terror (10 examples)
Security threat scenarios:
- Bomb threats at transportation hubs
- Armed individuals near government buildings
- Explosive devices in public spaces
- Suspicious powder/CBRN alerts
- Threats targeting institutions
- Intelligence-based alerts
- Unattended baggage
- Border security incidents
- Civil aviation threats

### Infrastructure (10 examples)
Critical infrastructure failures:
- Power grid outages
- Water treatment failures
- Bridge structural issues
- Gas pipeline leaks
- Railway signal system failures
- Sewage system overflows
- Hospital heating breakdowns
- Telecom tower collapses
- Port equipment malfunction
- Airport runway damage

### Traffic (10 examples)
Transportation incidents:
- Multi-vehicle pile-ups
- Road hazmat spills
- Traffic signal malfunctions
- Vehicle fires
- Heavy vehicle breakdowns
- Construction-related closures
- Railway crossing malfunctions
- Special event road closures

## Quick Start

### Prerequisites

1. Ensure the Crisis Management API is running:
   ```bash
   python main.py
   ```

2. Install dependencies (if not already installed):
   ```bash
   pip install httpx
   ```

### Sending All Incidents

Send all 50 example incidents to the API:

```bash
python examples/send_incidents.py
```

### Sending to Non-Standard Port

If your API is running on a different port (e.g., 8080):

```bash
python examples/send_incidents.py --api-url http://localhost:8080
```

### Expected Output

```
Found 50 incident files
API base URL: http://localhost:8080
--------------------------------------------------------------------------------
✓ cyber_01.json                 incident_id=incident_6f7c4a2b
✓ cyber_02.json                 incident_id=incident_8d2e5b9a
✓ cyber_03.json                 incident_id=incident_4c1f6e3d
...
✓ traffic_10.json               incident_id=incident_9k3p8l2m
--------------------------------------------------------------------------------
Sent 50 incidents: 50 success, 0 errors
```

## Incident Payload Structure

Each JSON file follows the `IncidentInput` schema:

```json
{
  "timestamp": "2026-05-19T10:30:00Z",
  "location": {
    "voivodeship": "mazowieckie",
    "county": "Warsaw",
    "municipality": "Warsaw",
    "coordinates": {
      "lat": 52.2297,
      "lon": 21.0122
    }
  },
  "description": "Incident description...",
  "source": {
    "type": "citizen|institution|sensor|social_media",
    "reporter_id": "unique_reporter_id",
    "channel": "mobile_app|official_hotline|automated_system|x_platform"
  },
  "media_refs": [
    {
      "type": "photo|video|document",
      "url": "https://example.com/media.jpg"
    }
  ]
}
```

## Testing Workflows

### Test 1: Single Category Load Test
```bash
python -c "
import json
from pathlib import Path

incidents = list(Path('examples/incidents').glob('cyber_*.json'))
print(f'Cyber incidents: {len(incidents)}')
for f in incidents[:3]:
    with open(f) as fp:
        data = json.load(fp)
        print(f'- {f.name}: {data[\"description\"][:50]}...')
"
```

### Test 2: Monitor API Response
Open another terminal and watch SSE stream for an incident:

```bash
# After sending incidents, get one incident_id from output
curl http://localhost:8080/viz/stream/{incident_id}
```

### Test 3: Check Realtime Metrics
```bash
curl http://localhost:8080/api/v1/metrics/live?window_minutes=5
```

## Performance Notes

- Script sends incidents sequentially with 0.1s delay per request
- For mass testing (>100 requests/sec), consider async batching
- Monitor API logs for processing latency
- Check `/health` endpoint for GPU utilization

## Troubleshooting

### Connection refused
```
✗ incident.json            Error: Connection refused
```
- Ensure API is running: `python main.py`
- Verify correct API URL with `--api-url` parameter

### Invalid JSON
```
✗ incident.json            Error: 422 Unprocessable Entity
```
- Check incident file format matches `IncidentInput` schema
- Verify coordinates are realistic (lat: -90 to 90, lon: -180 to 180)
- Ensure description is at least 10 characters

### Timeout
```
✗ incident.json            Error: Timeout
```
- API may be overloaded
- Increase timeout in `send_incidents.py` (line ~40)
- Reduce parallelization or add delays

## Creating Custom Incidents

Create a new incident JSON file:

```json
{
  "timestamp": "2026-05-19T14:00:00Z",
  "location": {
    "voivodeship": "dolnoslaskie",
    "county": "wroclawski",
    "municipality": "Wroclaw",
    "coordinates": {
      "lat": 51.1079,
      "lon": 17.0385
    }
  },
  "description": "Your custom incident description with sufficient detail (min 10 chars).",
  "source": {
    "type": "citizen",
    "reporter_id": "custom_reporter_001",
    "channel": "mobile_app"
  },
  "media_refs": []
}
```

Then send it:
```bash
python -c "
import json
import httpx
with open('examples/incidents/custom_incident.json') as f:
    data = json.load(f)
response = httpx.post('http://localhost:8080/api/v1/incidents', json=data)
print(response.json())
"
```

## Notes

- All incidents reference realistic Polish locations (voivodeships, counties, cities)
- Coordinates are approximate (for GIS analysis purposes)
- Descriptions are realistic but fictional
- Incidents demonstrate variety of crisis scenarios
- Source types represent different data ingestion channels

## Support

For issues or questions:
1. Check API logs: `tail -f main.log`
2. Verify API health: `curl http://localhost:8080/health`
3. Review incident schema in `app/schemas.py`
4. Test single incident manually with curl or Postman

