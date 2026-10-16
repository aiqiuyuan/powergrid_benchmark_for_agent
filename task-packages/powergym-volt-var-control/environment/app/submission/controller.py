"""Hold current capacitor/tap settings and request idle battery power."""


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
        return capacitors + regulators + [self.idle] * self.batteries
