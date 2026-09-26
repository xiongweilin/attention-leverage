from datetime import datetime, timezone
import hashlib

from app.models import SourceProfile
from app.sources.base import Source
from app.sources.utils import parse_datetime, strip_html, xml_feed_entries


class StubSource(Source):
    profile = SourceProfile(name='feed', category='feeds', description='test feed')

    async def search(self, query, horizon_hours):
        return []


def test_parse_datetime_supported_formats_and_invalid_values():
    naive = datetime(2026, 1, 2, 3, 4, 5)
    aware = naive.replace(tzinfo=timezone.utc)

    assert parse_datetime(None) is None
    assert parse_datetime(aware) == aware
    assert parse_datetime(naive) == aware
    assert parse_datetime(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert parse_datetime((2026, 1, 2, 3, 4, 5, 0, 2, -1)) == aware
    assert parse_datetime('2026-01-02T03:04:05Z') == aware
    assert parse_datetime('2026-01-02T03:04:05') == aware
    assert parse_datetime('Fri, 02 Jan 2026 03:04:05 GMT') == aware
    assert parse_datetime('') is None
    assert parse_datetime('not a date') is None
    assert parse_datetime((2026, 1, 2)) is None
    assert parse_datetime(10 ** 100) is None
    assert parse_datetime(object()) is None


def test_strip_html_unescapes_and_collapses_whitespace():
    assert strip_html('<p> A&nbsp; &amp; <b>B</b> </p>') == 'A & B'
    assert strip_html(None) == ''


def test_xml_feed_entries_reads_rss_and_atom_and_joins_atom_links():
    content = b'''<rss><channel><item><title>News</title><link>https://example.test/n</link>
      <description>Short summary</description><pubDate>Fri, 02 Jan 2026 03:04:05 GMT</pubDate></item>
      <item><title>Summary fallback</title><summary>Fallback</summary><date>2026-01-02</date></item>
    </channel></rss>'''
    rss = xml_feed_entries(content)
    assert rss[0]['title'] == 'News'
    assert rss[0]['summary'] == 'Short summary'
    assert rss[1]['summary'] == 'Fallback'
    assert rss[1]['published'] == '2026-01-02'

    atom = b'''<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Atom title</title><link rel="self" href="/self"/>
        <link rel="alternate" href="/entry/1"/><summary>Abstract</summary>
        <published>2026-01-02T03:04:05Z</published></entry>
      <entry><title>Fallback link</title><link rel="self" href="/entry/2"/><content>Content</content>
        <updated>2026-01-03T00:00:00Z</updated></entry>
    </feed>'''
    entries = xml_feed_entries(atom, 'https://example.test/feed')
    assert entries[0]['link'] == 'https://example.test/entry/1'
    assert entries[0]['summary'] == 'Abstract'
    assert entries[1]['link'] == 'https://example.test/entry/2'
    assert entries[1]['summary'] == 'Content'
    assert xml_feed_entries(b'<rss>') == []


def test_source_item_id_remains_stable_and_uses_nonsecurity_hash_context():
    source = StubSource(object())
    item = source.item(title='A title', url='https://example.test/item', stable_key='external-id')
    expected = hashlib.sha1(b'feed\0external-id', usedforsecurity=False).hexdigest()[:20]

    assert item.id == expected
    assert item.metadata == {}
    assert item.source == 'feed'
