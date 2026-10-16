"""Voltage hysteresis starter; preserve capacitor states and idle batteries."""


class Controller:
    def __init__(self, metadata):
        self.capacitors = metadata["capacitor_count"]
        self.regulators = metadata["regulator_count"]
        self.batteries = metadata["battery_count"]
        continuous = metadata["continuous_batteries"]
        self.idle = 0.0 if continuous else metadata["battery_max"] // 2

    def act(self, observation):
        capacitors = list(observation["capacitor_states"])
        regulators = list(observation["regulator_taps"])
        if len(capacitors) != self.capacitors or len(regulators) != self.regulators:
            raise ValueError("Current device state does not match declared device counts")
        voltages = [value for row in observation["bus_voltages"].values() for value in row]
        direction = -1 if max(voltages) > 1.06 else (1 if min(voltages) < 0.94 else 0)
        regulators = [max(0, min(32, tap + direction)) for tap in regulators]
        return capacitors + regulators + [self.idle] * self.batteries
