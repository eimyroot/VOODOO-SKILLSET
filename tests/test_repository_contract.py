from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_readme_uses_repository_banner(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        banner = ROOT / "docs/assets/voodoo-skillset-banner.svg"
        self.assertTrue(banner.is_file())
        self.assertIn("docs/assets/voodoo-skillset-banner.svg", readme)
        self.assertIn("## Run the cockpit", readme)
        self.assertIn("make cockpit", readme)

    def test_cockpit_is_english_and_zero_build(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="en">', html)
        self.assertIn("VOODOO / SKILLSET", html)
        self.assertIn('/styles.css', html)
        self.assertIn('/app.js', html)

    def test_vercel_routes_root_and_api_to_canonical_adapters(self):
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        rewrites = {item["source"]: item["destination"] for item in config["rewrites"]}
        self.assertEqual(rewrites["/"], "/web/index.html")
        self.assertEqual(rewrites["/api/:path*"], "/api/index.py?route=:path*")

    def test_cockpit_launcher_uses_shared_cli_server(self):
        launcher = (ROOT / "scripts/cockpit.sh").read_text(encoding="utf-8")
        self.assertIn("voodoo_skillset.cli serve", launcher)
        self.assertIn('VOODOO_HOST', launcher)
        self.assertIn('VOODOO_PORT', launcher)

    def test_generated_local_state_is_ignored(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for pattern in (".env", "*.sqlite3", ".vercel/", "dist/", "*.egg-info/"):
            self.assertIn(pattern, ignore)


if __name__ == "__main__":
    unittest.main()
