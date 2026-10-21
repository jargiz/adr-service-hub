import sys
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'adr_service_agent'))
from presentation import present_html, display_text
from agent import Pilot, page
from service_report import run_checks


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.text = []; self.style = False
    def handle_starttag(self, tag, attrs):
        if tag == 'style': self.style = True
    def handle_endtag(self, tag):
        if tag == 'style': self.style = False
    def handle_data(self, data):
        if not self.style: self.text.append(data)


class PresentationTests(unittest.TestCase):
    def test_plain_copy_preserves_unknowns_and_operational_qualifiers(self):
        original = 'sensor.living_room: unavailable in HA; physical connectivity and cause remain unverified.'
        result = display_text(original)
        self.assertIn('Living room: unavailable', result)
        self.assertIn('physical connectivity and cause remain unverified', result)
        self.assertNotIn('sensor.', result)
        self.assertNotIn('HA', result)

    def test_html_escape_protocol_attributes_and_style_preserved(self):
        source = '<style>.entity{color:red}</style><form action="sense-discover"><input name="entity_id" value="sensor.l1"><button aria-label="Read HA entities">Home Assistant readings</button></form><p>&lt;script&gt;bad&lt;/script&gt;</p>'
        output = present_html(source)
        self.assertIn('<style>.entity{color:red}</style>', output)
        self.assertIn('name="entity_id" value="sensor.l1"', output)
        self.assertIn('aria-label="Read device readings"', output)
        self.assertIn('&lt;script&gt;bad&lt;/script&gt;', output)
        self.assertNotIn('<script>', output)
        self.assertNotIn('Home Assistant', output)

    def test_full_page_has_no_visible_platform_or_entity_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'options.json').write_text('{}')
            pilot = Pilot(root, root/'options.json')
            pilot.service_report, _ = run_checks([('Sonos', 'test', lambda: {'players': [
                {'name': 'media_player.living_room', 'state': 'unavailable'}]})], {})
            parser = TextParser(); parser.feed(page(pilot))
            text = ' '.join(parser.text)
            for forbidden in ('Home Assistant', 'HA ', 'media_player.'):
                self.assertNotIn(forbidden, text)
            self.assertIsNone(re.search(r'\bentities?\b', text, re.I))
            self.assertIn('unavailable', text)
            self.assertIn('unverified', text)


if __name__ == '__main__': unittest.main()
