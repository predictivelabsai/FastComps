"""Display taxonomy for clinic treatments collected across EEA markets.

The source offering is always retained unchanged. This taxonomy supplies a
stable reporting category when the upstream category is absent or explicitly
unmapped. It includes the 48-treatment MMG master-list families and broader
clinic-market groups needed by FastComps.
"""

from __future__ import annotations


TAXONOMY_VERSION = "2026-09-09"
UNMAPPED_LABELS = frozenset({"", "unmapped", "uncategorised", "uncategorized", "unknown", "other"})

# Ordered from specific procedures to broader concepts. Matching is intentionally
# conservative: raw treatment names remain in the database and UI at all times.
TREATMENT_TAXONOMY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Ophthalmology", (
        "ophthalm", "cataract", "retina", "cornea", "keratoplast", "trabeculot", "glaucoma",
        "vision", "eye ", "eyelid", "laser eye",
    )),
    ("Gynaecology & obstetrics", (
        "gynaec", "gynec", "hysterect", "myomect", "salpingo", "oophorect", "uter", "ovary",
        "ovarian", "cervi", "pregnan", "maternity", "obstetric", "fertility", "ivf", "colposcop",
        "vaginal", "caesarean", "cesarean", "childbirth",
    )),
    ("Urology", (
        "urolog", "prostate", "bladder", "kidney", "renal", "ureteroscop", "urethr", "vasectomy", "turbt", "turp",
        "cystopex", "urinary incontinence", "neuromodulation", "spermogram", "spermoculture",
    )),
    ("Cardiology & vascular", (
        "cardi", "coronary", "angioplast", "bypass graft", "pacemaker", "defibrillator", "heart",
        "vascular", "vein", "arter", "ecg", "ekg",
    )),
    ("ENT & thyroid", (
        "septoplast", "septorhinoplast", "thyroidect", " ent ", " ear ", "nose", "nasal", "sinus",
        "throat", "tonsil", "hearing", "audiolog",
    )),
    ("Cosmetic & corrective surgery", (
        "rhinoplast", "orthognath", "abdominoplast", "mammoplast", "mastopex", "fue", "facelift",
        "necklift", "brachioplast", "rhytidect", "breast lift", "breast enlargement", "hair transplant",
        "cosmetic", "aesthetic surgery", "plastic surgery", "liposuction", "breast augmentation",
        "breast reduction", "arm lift", "thigh lift", "tummy tuck", "inverted nipple", "fat transfer",
        "labiaplast", "genitalia", "russian lips",
    )),
    ("Orthopaedics & spine", (
        "knee replacement", "hip replacement", "ankle joint", "shoulder replacement", "arthroplast",
        "acl", "cruciate", "arthroscop", "hip resurfacing", "discect", "laminect", "orthop", "joint",
        "knee", " hip ", "spine", "scoliosis", "shoulder", "tendon", "femur", "ganglion", "bursa",
        "osteotom", "fracture", "bone tumor", "bone tumour", "trigger finger", "carpal", "tibial",
        "transpedicular", "spondyl", "plaster cast", "aparat gipsat", "ligament reconstruction",
    )),
    ("General surgery", (
        "bowel resection", "fundoplication", "gastric bypass", "gastrect", "cholecystect", "gallbladder",
        "hernia", "general surgery", "appendect", "colectom", "resection",
    )),
    ("Diagnostics & imaging", (
        "mri", "magnetic resonance", " ct ", "computed tomography", "x-ray", "xray", "ultrasound",
        "diagnostic", "imaging", "scan", "echo", "endoscop", "radiolog", "ecografie", "mammogram",
    )),
    ("Laboratory & pathology", (
        "blood", "laboratory", "patholog", "panel", "triglycer", "ferritin", "glucose", "haemoglobin",
        "hemoglobin", "urine", "allergy test", "biomarker", "histology", "smear", "culture", "calcium",
        "protein", "bilirubin", "testosterone", " tsh ",
    )),
    ("Dental & oral health", (
        "dental", "dentist", "tooth", "teeth", "implant", "orthodont", "crown", "root canal", "oral surgery",
    )),
    ("Dermatology & non-surgical aesthetics", (
        "dermat", "skin", "filler", "botox", "laser", "aesthetic", "beauty", "lipoma", "atheroma", "mole",
        "sclerotherap", "silhouette",
    )),
    ("Gastroenterology", ("gastro", "colonoscop", "gastroscop", "digestive", "liver", "pancrea")),
    ("Neurology & neurosurgery", ("neurolog", "neurosurg", "migraine", "epilep", "nerve", "brain")),
    ("Oncology", ("oncolog", "cancer", "tumour", "tumor", "chemotherap", "radiotherap")),
    ("Wellness & IV therapy", (
        " iv ", "infusion", "vitamin", "hydration", "longevity", "drip", "immune", "energy boost",
        "anti-stress", "recovery boost", "wellness",
    )),
    ("Rehabilitation & physiotherapy", (
        "physio", "rehabil", "massage", "mobility", "occupational therapy", "chiropract", "sports therapy",
        "treadmill", "gymnastics", "taping", " tens ", "tecar", "stairs", "shockwave",
    )),
    ("Mental health", ("psychi", "psycholog", "psychotherap", "therapy session", "counselling", "counseling")),
    ("Surgery & procedures", (
        "surgery", "surgical", "operation", "removal", "repair", "puncture", "injection", "biopsy",
        "ectomy", "plasty", "suture", "wound", "dressing", "sutură", "sutura",
    )),
    ("Consultations & general medicine", (
        "consult", "appointment", "examination", "visit", "second opinion", "check-up", "checkup",
        "on-call", "assessment", "screening", "package", "vaccination", "vaccine",
    )),
)

FALLBACK_CATEGORY = "General medicine & other treatments"


def classify_treatment(name: str | None, mapped: str | None = None) -> str:
    """Return a reporting category without altering the retained source value."""
    upstream = (mapped or "").strip()
    if upstream.casefold() not in UNMAPPED_LABELS:
        return upstream
    normalized = f" {(name or '').casefold()} "
    for category, terms in TREATMENT_TAXONOMY:
        if any(term in normalized for term in terms):
            return category
    return FALLBACK_CATEGORY
