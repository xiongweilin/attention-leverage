from __future__ import annotations

import calendar
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin


def strip_html(text: str) -> str:
    value = html.unescape(text or '')
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', value)).strip()


def parse_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    if isinstance(value, (int, float)):
        return _from_timestamp(value)
    if isinstance(value, tuple) and len(value) >= 6:
        return _from_time_tuple(value)
    if isinstance(value, str):
        return _from_string(value)
    return None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _from_timestamp(value: int | float) -> datetime | None:
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _from_time_tuple(value: tuple) -> datetime | None:
    try:
        return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _from_string(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    parsed = _parse_iso(normalized)
    if parsed is not None:
        return parsed
    try:
        return _as_utc(parsedate_to_datetime(normalized))
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_iso(value: str) -> datetime | None:
    candidates = (value, value.replace('Z', '+00:00'))
    for candidate in candidates:
        try:
            return _as_utc(datetime.fromisoformat(candidate))
        except ValueError:
            continue
    return None


def xml_feed_entries(content: bytes, base_url: str = '') -> list[dict]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    return _rss_entries(root) + _atom_entries(root, base_url)


def _rss_entries(root: ET.Element) -> list[dict]:
    return [{
            'title': _text(item, 'title'), 'link': _text(item, 'link'),
            'summary': _text(item, 'description') or _text(item, 'summary'),
            'published': _text(item, 'pubDate') or _text(item, 'date'),
        } for item in root.findall('.//item')]


def _atom_entries(root: ET.Element, base_url: str) -> list[dict]:
    return [{
            'title': _text_ns(entry, 'title'), 'link': urljoin(base_url, _atom_link(entry)),
            'summary': _text_ns(entry, 'summary') or _text_ns(entry, 'content'),
            'published': _text_ns(entry, 'published') or _text_ns(entry, 'updated'),
        } for entry in root.findall('.//{*}entry')]


def _atom_link(entry: ET.Element) -> str:
    links = entry.findall('{*}link')
    preferred = next((link for link in links if link.attrib.get('href')
                      and link.attrib.get('rel', 'alternate') in ('alternate', '')), None)
    selected = preferred if preferred is not None else next(
        (link for link in links if link.attrib.get('href')), None
    )
    return selected.attrib.get('href', '') if selected is not None else ''


def _text(el, tag: str) -> str:
    child = el.find(tag)
    return ''.join(child.itertext()).strip() if child is not None else ''


def _text_ns(el, tag: str) -> str:
    child = el.find(f'{{*}}{tag}')
    return ''.join(child.itertext()).strip() if child is not None else ''
