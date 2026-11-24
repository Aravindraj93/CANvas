"""Quick API smoke test against running CANvas backend."""
import httpx, json

BASE = "http://localhost:8765/api"

# Health check
r = httpx.get(f"{BASE}/health")
print("Health:", r.json())

# Upload DBC
with open("tests/fixtures/sample.dbc", "rb") as f:
    r = httpx.post(f"{BASE}/dbc/upload", files={"file": ("sample.dbc", f, "text/plain")})
body = r.json()
print(f"DBC Upload: {body['message_count']} messages")
for m in body['messages']:
    print(f"  {m['name']} ({m['arbitration_id_hex']}) — {len(m['signals'])} signals")

# Connect virtual bus
r = httpx.post(f"{BASE}/signals/bus/connect", json={"bus_type": "virtual"})
print("Bus Connect:", r.json())

# Send signal
r = httpx.post(f"{BASE}/signals/send", json={"message_name": "Powertrain", "signal_name": "VehicleSpeed", "value": 100.0})
print("Send Signal:", r.json())

# Run test
yaml_str = open("examples/fuel-warning-test.yaml").read()
r = httpx.post(f"{BASE}/tests/run", json={"test_yaml": yaml_str}, timeout=15.0)
result = r.json()
print(f"Test Run: {result['status']} ({result['passed']}/{result['total_steps']} passed)")

print("\nAll API smoke tests passed!")
