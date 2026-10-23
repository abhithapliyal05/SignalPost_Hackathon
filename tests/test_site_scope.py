from norway_company_agent.identity_index import IdentityIndex
from norway_company_agent.site_scope import METHOD, apply_site_scope_guard


def _site(url):
    return {"status": "available", "source_url": url, "value": {
        "final_url": url,
        "identity_assessment": {"publishable": True, "status": "exact", "reasons": ["x"]},
        "social_links": [{"platform": "facebook", "url": "https://facebook.com/x"}],
    }}


def _index(**domains):
    index = IdentityIndex()
    index.homepage_domains.update(domains)
    return index


def test_shared_domain_is_withheld_with_its_social_links():
    site = apply_site_scope_guard(_site("https://bestseller.com/"), _index(**{"bestseller.com": 7}))
    value = site["value"]
    assert not value["identity_assessment"]["publishable"]
    assert value["social_links"] == [] and value["withheld_by"] == METHOD
    assert value["withheld_social_links"]


def test_locale_section_on_foreign_domain_is_withheld():
    site = apply_site_scope_guard(_site("https://www.rittal.com/no-no/"), _index())
    assert not site["value"]["identity_assessment"]["publishable"]


def test_own_unique_domain_and_no_locale_path_are_kept():
    own = apply_site_scope_guard(_site("https://pretre.no/no/"), _index(**{"pretre.no": 1}))
    assert own["value"]["identity_assessment"]["publishable"] and own["value"]["social_links"]


def test_job_ad_points_at_its_own_nav_page_not_a_careers_link():
    from norway_company_agent.jobs import single_ad_view

    careers = single_ad_view({"uuid": "abc", "link": "https://firma.no/karriere"})
    assert careers["ad_url"].endswith("/stilling/abc") and careers["link"] is None and careers["employer_link_dropped"]
    own = single_ad_view({"uuid": "abc", "link": "https://arbeidsplassen.nav.no/stillinger/stilling/abc"})
    assert own["link"] == own["ad_url"] and not own["employer_link_dropped"]


def test_short_name_token_inside_long_handle_is_not_enough():
    from norway_company_agent.site_scope import social_handle_is_distinctive

    profile = {"name": "ROM AS"}
    assert not social_handle_is_distinctive(profile, "https://facebook.com/rominteriorarkitekter")
    assert social_handle_is_distinctive({"name": "BOLIGTEKST AS"}, "https://facebook.com/Boligtekst")
    assert social_handle_is_distinctive({"name": "VASK OG BAD AS"}, "https://instagram.com/vaskogbad")


def test_handle_spelling_the_verified_domain_is_kept():
    site = _site("https://nordanger.no/")
    site["value"]["identity_assessment"]["method"] = "strict_free_candidate_proof_v1"
    site["value"]["social_links"] = []
    site["value"]["discovered_social_links"] = [
        {"platform": "facebook", "url": "https://facebook.com/nordanger.no"},
        {"platform": "facebook", "url": "https://facebook.com/someagency"},
    ]
    apply_site_scope_guard(site, _index(**{"nordanger.no": 1}), {"name": "NORDANGER GULV AS"})
    assert site["value"]["social_links"] == [{"platform": "facebook", "url": "https://facebook.com/nordanger.no"}]


def test_company_posts_use_item_dates_and_same_domain_only():
    from norway_company_agent.site_posts import parse_feed

    feed = b"""<?xml version="1.0"?><rss><channel><lastBuildDate>Wed, 22 Oct 2026 10:00:00 GMT</lastBuildDate>
    <item><title>Ny avtale</title><link>https://firma.no/nyheter/ny-avtale</link><pubDate>Mon, 06 Oct 2026 08:00:00 GMT</pubDate></item>
    <item><title>Undated</title><link>https://firma.no/x</link></item>
    <item><title>Elsewhere</title><link>https://other.no/y</link><pubDate>Mon, 06 Oct 2026 08:00:00 GMT</pubDate></item>
    </channel></rss>"""
    posts = parse_feed(feed, "https://firma.no/feed")
    assert [post["title"] for post in posts] == ["Ny avtale"]
    assert posts[0]["published_at"] == "2026-10-06T08:00:00Z"
    assert parse_feed(b'<!DOCTYPE x [<!ENTITY a "b">]><rss/>', "https://firma.no/feed") == []
