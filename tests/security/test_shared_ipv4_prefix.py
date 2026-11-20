"""The public shared network prefix is distinct from device addresses."""
import sys
import unittest
from ipaddress import IPv4Network
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Special._security._checks import inspect  # noqa: E402
from Special._security._me import Policy  # noqa: E402


class SharedPrefixTests(unittest.TestCase):
    def test_shared_ipv4_prefix_is_public_but_device_addresses_are_reported(self):
        network = IPv4Network("100.64.0.0/10")
        endpoint = str(network.network_address + 1)
        self.assertFalse(inspect(str(network), "fixture", Policy()))
        for sample in (str(network.network_address), endpoint, endpoint + "/10", str(network) + "0"):
            self.assertTrue(any(item.check == "tailnet address" for item in inspect(sample, "fixture", Policy())))
        policy = Policy(identities={"never-publish": [str(network)]})
        self.assertTrue(any(item.check == "never-publish" for item in inspect(str(network), "fixture", policy)))


if __name__ == "__main__":
    unittest.main()
