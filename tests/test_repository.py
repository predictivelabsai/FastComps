import repository


def test_unmapped_treatments_receive_conservative_display_groups():
    assert repository.treatment_type("Whole body MRI scan") == "Diagnostics & imaging"
    assert repository.treatment_type("Vitamin C infusion") == "Wellness & IV therapy"
    assert repository.treatment_type("Clinic package alpha") == "Other treatments"
    assert repository.treatment_type("MRI scan", "Radiology") == "Radiology"
    assert repository.treatment_type("MRI scan", "Unmapped") == "Diagnostics & imaging"
    assert repository.treatment_type("Clinic package alpha") != "Unmapped"


def test_coverage_uses_real_campaign_states():
    base = {"verified": 0, "target": 10, "candidates": 0}
    assert repository.coverage_status({**base, "campaign_status": "queued"}) == "queued"
    assert repository.coverage_status({**base, "campaign_status": "running"}) == "running"
    assert repository.coverage_status({**base, "campaign_status": "not_started"}) == "not_started"
    assert repository.coverage_status({**base, "campaign_status": "complete", "candidates": 2}) == "review_required"
    assert repository.coverage_status({**base, "campaign_status": "running", "verified": 10}) == "covered"
