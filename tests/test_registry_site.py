from norway_company_agent.identity_index import IdentityIndex, homepage_domain
from norway_company_agent.registry_site import METHOD, apply_registry_declared_rule

TEXT = "Pretre leverer takstoler, precut, bjelkelag og konstruksjonspakker til byggebransjen over hele landet. " * 3


def _index(**domains):
    index = IdentityIndex()
    index.homepage_domains.update(domains)
    return index


def _profile(name="PRETRE AS", website="www.pretre.no", group=False):
    return {
        "organisation_number": "884647762",
        "name": name,
        "website": website,
        "evidence": {
            "registry": {"value": {"erIKonsern": "true" if group else "false"}},
            "group": {"status": "not_found"},
            "locations": {"value": {"locations": []}},
        },
    }


def _site(final_url="https://www.pretre.no/", text=TEXT, title="Pretre - bærende konstruksjoner"):
    return {
        "status": "available",
        "value": {
            "final_url": final_url,
            "title": title,
            "main_text_excerpt": text,
            "pages": [],
            "identity_assessment": {"publishable": False, "method": "deterministic_name_org_evidence_v2"},
            "discovered_social_links": [{"platform": "facebook", "url": "https://www.facebook.com/pretre"}],
        },
    }


def test_homepage_domain_normalizes_registry_values():
    assert homepage_domain("www.Pretre.no/om-oss") == "pretre.no"
    assert homepage_domain("") is None


def test_unique_declared_domain_with_name_is_published():
    site = apply_registry_declared_rule(_profile(), _site(), _index(**{"pretre.no": 1}))
    assessment = site["value"]["identity_assessment"]
    assert assessment["publishable"] and assessment["method"] == METHOD
    assert site["value"]["kit_identity_assessment"]["publishable"] is False
    assert site["value"]["social_links"] == [{"platform": "facebook", "url": "https://www.facebook.com/pretre"}]


def test_shared_domain_is_rejected():
    site = apply_registry_declared_rule(_profile(), _site(), _index(**{"pretre.no": 2}))
    assert not site["value"]["identity_assessment"]["publishable"]
    assert not site["value"]["registry_declared_check"]["checks"]["unique_domain"]


def test_group_member_is_rejected():
    site = apply_registry_declared_rule(_profile(group=True), _site(), _index(**{"pretre.no": 1}))
    assert not site["value"]["identity_assessment"]["publishable"]


def test_foreign_orgnr_and_parked_pages_are_rejected():
    foreign = apply_registry_declared_rule(_profile(), _site(text=TEXT + " Org.nr 923 609 016"), _index(**{"pretre.no": 1}))
    assert foreign["value"]["registry_declared_check"]["foreign_orgnrs"] == ["923609016"]
    parked = apply_registry_declared_rule(_profile(), _site(text=TEXT + " This domain has expired."), _index(**{"pretre.no": 1}))
    assert not parked["value"]["registry_declared_check"]["checks"]["live_content"]


def test_generic_name_tokens_do_not_count():
    site = apply_registry_declared_rule(_profile(name="NORGE INVEST AS", website="www.norgeinvest.no"), _site(final_url="https://www.norgeinvest.no/"), _index(**{"norgeinvest.no": 1}))
    assert not site["value"]["registry_declared_check"]["checks"]["name_in_domain"]


def test_redirect_only_to_undeclared_named_domain():
    profile = _profile(name="RUNAR KVANT AS", website="www.runarkvant.no")
    ok = apply_registry_declared_rule(profile, _site(final_url="https://kvant.no/"), _index(**{"runarkvant.no": 1}))
    assert ok["value"]["identity_assessment"]["publishable"]
    taken = apply_registry_declared_rule(_profile(name="RUNAR KVANT AS", website="www.runarkvant.no"), _site(final_url="https://kvant.no/"), _index(**{"runarkvant.no": 1, "kvant.no": 1}))
    assert not taken["value"]["identity_assessment"]["publishable"]


def test_kit_published_site_is_left_alone():
    site = _site()
    site["value"]["identity_assessment"] = {"publishable": True, "method": "deterministic_name_org_evidence_v2"}
    apply_registry_declared_rule(_profile(), site, _index())
    assert "registry_declared_check" not in site["value"]


def test_national_subsidiary_declaring_foreign_brand_site_is_rejected():
    profile = _profile(name="BRADY ENERGY NORWAY AS", website="www.bradytechnologies.com")
    site = apply_registry_declared_rule(profile, _site(final_url="https://www.bradytechnologies.com/"), _index(**{"bradytechnologies.com": 1}))
    assert not site["value"]["registry_declared_check"]["checks"]["not_foreign_parent_site"]
    assert not site["value"]["identity_assessment"]["publishable"]
