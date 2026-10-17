import json
import unittest
import urllib.parse
from html.parser import HTMLParser

import app_setup


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.form = {}
        self.inputs = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form":
            self.form = values
        elif tag == "input":
            self.inputs[values["name"]] = values["value"]


class AppManifestTests(unittest.TestCase):
    def test_submitted_form_includes_required_homepage_and_disabled_webhook_url(self):
        parser = FormParser()
        parser.feed(app_setup.registration_form("http://127.0.0.1:8771", "test-state"))
        self.assertEqual(parser.form["method"], "post")
        action = urllib.parse.urlparse(parser.form["action"])
        self.assertEqual((action.scheme, action.netloc, action.path),
                         ("https", "github.com", "/organizations/arteamis-system/settings/apps/new"))
        self.assertEqual(urllib.parse.parse_qs(action.query), {"state": ["test-state"]})
        manifest = json.loads(parser.inputs["manifest"])
        for url in (manifest["url"], manifest["hook_attributes"]["url"]):
            self.assertEqual(url, "https://github.com/arteamis-system/platform")
        self.assertFalse(manifest["hook_attributes"]["active"])
        self.assertFalse(manifest["public"])
        self.assertEqual(manifest["default_events"], [])
        self.assertEqual(manifest["redirect_url"], "http://127.0.0.1:8771/callback")
        self.assertEqual(manifest["setup_url"], "http://127.0.0.1:8771/installed?state=test-state")
        self.assertEqual(manifest["default_permissions"], {
            "actions": "write", "administration": "write", "checks": "read", "contents": "read",
            "metadata": "read", "pull_requests": "read", "actions_variables": "write",
        })


if __name__ == "__main__":
    unittest.main()
