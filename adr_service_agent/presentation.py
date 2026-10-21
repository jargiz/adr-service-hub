"""Plain product language without exposing internal platform identifiers."""
import html
import re
from html.parser import HTMLParser


def display_text(value):
    text = str(value)
    phrases = (
        ('Home Assistant Devices & services', 'connection settings'),
        ('Home Assistant ingress', 'authorized app access'),
        ('Home Assistant API access', 'system data access'),
        ('through Home Assistant', 'from your system connections'),
        ('in Home Assistant', 'in connection settings'),
        ('Home Assistant metadata', 'saved device information'),
        ('Home Assistant', 'system connection'),
        ('HA recorder history', 'Recorded history'),
        ('HA recorder', 'recorded history'),
        ('HA reported state', 'Reported state'),
        ('Last HA update', 'Last reported update'),
        ('HA last-update', 'Last-update'),
        ('HA integration state', 'Connection state'),
        ('HA state snapshots', 'Reported snapshots'),
        ('HA states', 'reported states'),
        ('HA state', 'reported state'),
        ('HA readings', 'device readings'),
        ('HA reading', 'device reading'),
        ('HA entities', 'device readings'),
        ('HA entity', 'device reading'),
        ('HA registry', 'device inventory'),
        ('HA snapshot', 'reported snapshot'),
        ('in HA', 'in the latest report'),
    )
    for before, after in phrases:
        text = re.sub(r'\b' + re.escape(before) + r'\b', after, text, flags=re.I)
    text = re.sub(r'\bHA\b', 'system', text)
    text = re.sub(r'\bhomeassistant\b', 'service hub', text, flags=re.I)
    text = re.sub(r'\bentities\b', 'readings', text, flags=re.I)
    text = re.sub(r'\bentity\b', 'reading', text, flags=re.I)
    # Display a readable label when an upstream friendly name was absent.
    text = re.sub(r'\b(?:sensor|binary_sensor|media_player|light|switch|climate|cover|button|scene|device_tracker|lock)\.([a-z0-9_]+)\b',
        lambda match: match[1].replace('_', ' ').capitalize(), text)
    return text


class ProductHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output = []
        self.verbatim = 0

    def handle_starttag(self, tag, attrs):
        source = self.get_starttag_text()
        for key in ('title', 'aria-label', 'placeholder', 'alt'):
            pattern = r'(\s' + key + r'\s*=\s*)([\"\'])(.*?)(\2)'
            source = re.sub(pattern, lambda match: match[1] + match[2] + html.escape(display_text(html.unescape(match[3])), quote=True) + match[2], source, flags=re.I)
        self.output.append(source)
        if tag in ('style', 'script'):
            self.verbatim += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        self.output.append('</' + tag + '>')
        if tag in ('style', 'script'):
            self.verbatim = max(0, self.verbatim - 1)

    def handle_data(self, data):
        self.output.append(data if self.verbatim else display_text(data))

    def handle_entityref(self, name):
        self.output.append('&' + name + ';')

    def handle_charref(self, name):
        self.output.append('&#' + name + ';')

    def handle_decl(self, decl):
        self.output.append('<!' + decl + '>')

    def handle_comment(self, data):
        self.output.append('<!--' + data + '-->')


def present_html(source):
    parser = ProductHTML()
    parser.feed(source)
    parser.close()
    return ''.join(parser.output)
