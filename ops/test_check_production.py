import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("check_production", Path(__file__).with_name("check-production.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseChecks(unittest.TestCase):
    def healthy(self):
        return {"arteamis-backend": {"Running": True}, "arteamis-worker": {"Running": True},
                "arteamis-postgres": {"Health": {"Status": "healthy"}},
                "disk_used_percent": 50, "backup_age_hours": 1,
                "standalone_plane_running": False}

    def test_complete_evidence_passes(self):
        self.assertTrue(all(module.assess(self.healthy(), 200, 30).values()))

    def test_missing_or_old_backup_stops_release(self):
        for age in [None, 25]:
            metadata = self.healthy()
            metadata["backup_age_hours"] = age
            self.assertFalse(module.assess(metadata, 200, 30)["backup_within_24_hours"])

    def test_unknown_state_cannot_pass(self):
        self.assertFalse(any(module.assess({}, None, None).values()))


if __name__ == "__main__":
    unittest.main()
