from app.filtering import balanced_cap
from app.models import RawItem


def test_balanced_cap_preserves_heterogeneous_sources():
    items = [
        RawItem(id=f"a{i}", source="a", title=str(i), url=f"https://a/{i}") for i in range(10)
    ] + [
        RawItem(id=f"b{i}", source="b", title=str(i), url=f"https://b/{i}") for i in range(3)
    ]
    out = balanced_cap(items, 6)
    assert [x.source for x in out] == ["a", "b", "a", "b", "a", "b"]
