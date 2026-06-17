"""Categories router - read-only listing with parent → children tree."""


async def test_categories_returns_parent_children_tree(client):
    r = await client.get("/api/categories")
    assert r.status_code == 200
    cats = r.json()
    assert isinstance(cats, list) and cats, "seed_categories should populate parents"

    # Shape contract every parent row honours.
    sample = cats[0]
    assert {"id", "name", "slug", "icon", "children"} <= sample.keys()
    assert isinstance(sample["children"], list)


async def test_categories_children_carry_required_fields(client):
    cats = (await client.get("/api/categories")).json()
    parents_with_kids = [c for c in cats if c["children"]]
    assert parents_with_kids, "at least one seeded parent should have children"

    child = parents_with_kids[0]["children"][0]
    assert {"id", "name", "slug", "icon"} <= child.keys()
    # Parent never appears in its own children list.
    assert child["id"] != parents_with_kids[0]["id"]
