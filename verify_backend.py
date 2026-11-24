import sys
sys.path.insert(0, '.')

from backend.can.bus_manager import bus_manager
from backend.can.signal_sender import signal_sender
from backend.runner.test_runner import run_test_from_yaml
from backend.runner.reporter import generate_html_report
from backend.ai.test_generator import generate_test_yaml
print("All backend modules import OK")

# Load sample DBC
result = signal_sender.load_dbc('tests/fixtures/sample.dbc')
print("DBC loaded: {} messages".format(result['message_count']))
for m in result['messages']:
    print("  {} ({}) - {} signals".format(m['name'], m['arbitration_id_hex'], len(m['signals'])))

# Connect virtual bus
status = bus_manager.connect(bus_type='virtual')
print("Bus connected:", status.connected, "type:", status.bus_type)

# Send a signal
ok = signal_sender.send_signal('Powertrain', 'VehicleSpeed', 120.0)
print("Signal sent OK:", ok)

# Run the fuel warning test
import asyncio

yaml_content = open('examples/fuel-warning-test.yaml').read()

async def run():
    return await run_test_from_yaml(yaml_content)

results = asyncio.run(run())
print("Test status:", results['status'])
print("Steps passed: {}/{}".format(results['passed'], results['total_steps']))
for step in results['steps']:
    icon = 'PASS' if step['status'] == 'PASS' else 'FAIL'
    print("  [{}] {} - {}".format(icon, step['action'], step['message']))

# Generate HTML report
generate_html_report(results, 'canvas-report.html')
print("Report saved: canvas-report.html")

bus_manager.disconnect()
print("Done!")
