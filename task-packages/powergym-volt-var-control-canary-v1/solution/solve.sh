#!/bin/sh
set -eu
mkdir -p /app/submission
cat > /app/submission/controller.py <<'PY'
class Controller:
    def __init__(self, metadata):
        self.batteries = metadata['battery_count']

    def act(self, observation):
        volts = [v for row in observation['bus_voltages'].values() for v in row]
        direction = -1 if max(volts) > 1.06 else (1 if min(volts) < .94 else 0)
        return (list(observation['capacitor_states'])
                + [max(0, min(32, v+direction)) for v in observation['regulator_taps']]
                + [16] * self.batteries)
PY
