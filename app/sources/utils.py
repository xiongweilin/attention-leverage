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
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, tuple) and len(value) >= 6:
        return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        for candidate in (value, value.replace('Z', '+00:00')):
            try:
                dt = datetime.fromisoformat(candidate)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        try:
            dt = parsedate_to_datetime(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def xml_feed_entries(content: bytes, base_url: str = '') -> list[dict]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    out: list[dict] = []
    for item in root.findall('.//item'):
        out.append({
            'title': _text(item, 'title'), 'link': _text(item, 'link'),
            'summary': _text(item, 'description') or _text(item, 'summary'),
            'published': _text(item, 'pubDate') or _text(item, 'date'),
        })
    for entry in root.findall('.//{*}entry'):
        link = ''
        for link_el in entry.findall('{*}link'):
            href = link_el.attrib.get('href', '')
            rel = link_el.attrib.get('rel', 'alternate')
            if href and rel in ('alternate', ''):
                link = href; break
            if href and not link:
                link = href
        out.append({
            'title': _text_ns(entry, 'title'), 'link': urljoin(base_url, link),
            'summary': _text_ns(entry, 'summary') or _text_ns(entry, 'content'),
            'published': _text_ns(entry, 'published') or _text_ns(entry, 'updated'),
        })
    return out


def _text(el, tag: str) -> str:
    child = el.find(tag)
    return ''.join(child.itertext()).strip() if child is not None else ''


def _text_ns(el, tag: str) -> str:
    child = el.find(f'{{*}}{tag}')
    return ''.join(child.itertext()).strip() if child is not None else ''
