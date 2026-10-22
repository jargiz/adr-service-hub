"""Small inline outline icons for the local dashboard."""

PATHS = {
    'home': '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    'power': '<path d="M12 3v8M6.3 5.8a9 9 0 1 0 11.4 0"/>',
    'energy': '<path d="m13 2-8 12h6l-1 8 9-13h-6z"/>',
    'network': '<rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 17.5h.01M11 17.5h.01M12 14v-4M8 10a6 6 0 0 1 8 0M5 7a10 10 0 0 1 14 0M2 4a15 15 0 0 1 20 0"/>',
    'wireless': '<path d="M3 7a15 15 0 0 1 18 0M6 11a10 10 0 0 1 12 0M9 15a5 5 0 0 1 6 0M12 19h.01"/>',
    'av': '<rect x="3" y="3" width="18" height="14" rx="2"/><path d="M8 21h8M12 17v4m-2-11 5 3-5 3z"/>',
    'audio': '<path d="m11 4-6 5H2v6h3l6 5zM15 8a6 6 0 0 1 0 8M18 5a10 10 0 0 1 0 14"/>',
    'processor': '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/><rect x="9" y="9" width="6" height="6" rx="1"/>',
    'switch': '<rect x="2" y="5" width="20" height="14" rx="3"/><path d="M6 10h2m3 0h2m3 0h2M6 14h2m3 0h2m3 0h2"/>',
    'settings': '<circle cx="12" cy="12" r="3"/><path d="m10 3-1 3-3 1-3-1-1 3 2 3-1 3 2 2 3-1 3 2 1 3 3-1 1-3 3-1 1-3-2-2 1-3-3-1-2-3z"/>',
    'history': '<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v6l4 2"/>',
    'chevron': '<path d="m9 5 7 7-7 7"/>',
}


def icon(name):
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + PATHS.get(name, PATHS['home']) + '</svg>'
