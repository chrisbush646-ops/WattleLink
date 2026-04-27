"""
Idempotent seed command — inserts 8 sample papers from the WattleLink prototype.
Checks DOI before creating; safe to run multiple times.
"""
import datetime

from django.core.management.base import BaseCommand

from apps.accounts.models import Tenant
from apps.literature.models import Paper


PAPERS = [
    {
        "title": (
            "Long-term safety profile of TNF-α inhibitors in moderate-to-severe RA: "
            "7-year registry outcomes"
        ),
        "authors": ["Hughes W", "Park H", "Reinhardt T", "et al."],
        "journal": "New England Journal of Medicine",
        "journal_short": "NEJM",
        "published_date": datetime.date(2026, 3, 14),
        "volume": "394",
        "issue": "11",
        "pages": "1241-1252",
        "doi": "10.1056/NEJMoa2601234",
        "study_type": Paper.StudyType.RCT,
        "source": Paper.Source.PDF_UPLOAD,
        "status": Paper.Status.APPROVED,
        "grade_rating": Paper.GradeRating.HIGH,
    },
    {
        "title": (
            "Real-world evidence for biosimilar uptake across Australian public hospitals, "
            "2020–2025"
        ),
        "authors": ["O'Donnell J", "Nguyen M", "et al."],
        "journal": "Medical Journal of Australia",
        "journal_short": "MJA",
        "published_date": datetime.date(2026, 2, 28),
        "volume": "224",
        "issue": "4",
        "pages": "58-65",
        "doi": "10.5694/mja2.52289",
        "study_type": Paper.StudyType.OBSERVATIONAL,
        "source": Paper.Source.PUBMED_OA,
        "status": Paper.Status.SUMMARISED,
        "grade_rating": Paper.GradeRating.MODERATE,
    },
    {
        "title": (
            "Emerging JAK-STAT targets in moderate-to-severe atopic dermatitis: "
            "meta-analysis of 12 phase III trials"
        ),
        "authors": ["Reinhardt T", "Chen A", "Okonkwo A", "et al."],
        "journal": "The Lancet",
        "journal_short": "Lancet",
        "published_date": datetime.date(2026, 1, 22),
        "volume": "407",
        "issue": "10375",
        "pages": "201-214",
        "doi": "10.1016/S0140-6736(25)02891-4",
        "study_type": Paper.StudyType.META_ANALYSIS,
        "source": Paper.Source.PDF_UPLOAD,
        "status": Paper.Status.ASSESSED,
        "grade_rating": Paper.GradeRating.HIGH,
    },
    {
        "title": (
            "Comparative efficacy of IL-23 blockade versus IL-17A in plaque psoriasis: "
            "network meta-analysis"
        ),
        "authors": ["Schmidt L", "Alvarez P", "et al."],
        "journal": "JAMA Dermatology",
        "journal_short": "JAMA Dermatol",
        "published_date": datetime.date(2026, 3, 2),
        "volume": "162",
        "issue": "3",
        "pages": "335-346",
        "doi": "10.1001/jamadermatol.2025.5678",
        "study_type": Paper.StudyType.META_ANALYSIS,
        "source": Paper.Source.PUBMED_OA,
        "status": Paper.Status.ASSESSED,
        "grade_rating": Paper.GradeRating.MODERATE,
    },
    {
        "title": (
            "Infusion-related reactions with anti-CD20 therapy: incidence and management "
            "in ANZ registry data"
        ),
        "authors": ["Khan R", "Wu L", "et al."],
        "journal": "Haematologica",
        "journal_short": "Haematologica",
        "published_date": datetime.date(2026, 2, 8),
        "volume": "111",
        "issue": "2",
        "pages": "412-421",
        "doi": "10.3324/haematol.2025.287654",
        "study_type": Paper.StudyType.OBSERVATIONAL,
        "source": Paper.Source.PUBMED_OA,
        "status": Paper.Status.INGESTED,
        "grade_rating": "",
    },
    {
        "title": (
            "Herpes zoster reactivation rates in patients on JAK-STAT inhibition: "
            "pooled analysis"
        ),
        "authors": ["Ng M", "Torres D", "Park H", "et al."],
        "journal": "Rheumatology",
        "journal_short": "Rheumatology",
        "published_date": datetime.date(2026, 1, 30),
        "volume": "65",
        "issue": "1",
        "pages": "89-98",
        "doi": "10.1093/rheumatology/keab987",
        "study_type": Paper.StudyType.META_ANALYSIS,
        "source": Paper.Source.PDF_UPLOAD,
        "status": Paper.Status.INGESTED,
        "grade_rating": "",
    },
    {
        "title": (
            "Patient-reported outcomes in long-duration biologic therapy: "
            "5-year qualitative study"
        ),
        "authors": ["Bianchi S", "et al."],
        "journal": "BMJ Open",
        "journal_short": "BMJ Open",
        "published_date": datetime.date(2026, 1, 11),
        "volume": "16",
        "issue": "1",
        "pages": "e078234",
        "doi": "10.1136/bmjopen-2025-078234",
        "study_type": Paper.StudyType.OBSERVATIONAL,
        "source": Paper.Source.PUBMED_OA,
        "status": Paper.Status.INGESTED,
        "grade_rating": "",
    },
    {
        "title": (
            "Healthcare resource utilisation in biosimilar-naive versus biosimilar-exposed "
            "populations"
        ),
        "authors": ["Green H", "Zhao W", "et al."],
        "journal": "PharmacoEconomics",
        "journal_short": "PharmacoEconomics",
        "published_date": datetime.date(2026, 1, 4),
        "volume": "44",
        "issue": "1",
        "pages": "33-45",
        "doi": "10.1007/s40273-025-01432-8",
        "study_type": Paper.StudyType.OBSERVATIONAL,
        "source": Paper.Source.PUBMED_OA,
        "status": Paper.Status.AWAITING_UPLOAD,
        "grade_rating": "",
    },
]


class Command(BaseCommand):
    help = "Seed 8 sample papers from the WattleLink prototype (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            default="Sample Tenant",
            help="Tenant name to seed into (created if absent)",
        )

    def handle(self, *args, **options):
        tenant_name = options["tenant"]
        tenant, created = Tenant.objects.get_or_create(
            name=tenant_name,
            defaults={"slug": tenant_name.lower().replace(" ", "-")},
        )
        if created:
            self.stdout.write(f"  Created tenant: {tenant.name}")
        else:
            self.stdout.write(f"  Using tenant:   {tenant.name}")

        created_count = 0
        skipped_count = 0

        for data in PAPERS:
            doi = data["doi"]
            exists = Paper.all_objects.filter(tenant=tenant, doi=doi).exists()
            if exists:
                skipped_count += 1
                self.stdout.write(f"  skip  {doi}")
                continue

            Paper.all_objects.create(tenant=tenant, **data)
            created_count += 1
            self.stdout.write(self.style.SUCCESS(f"  added {doi}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone — {created_count} created, {skipped_count} skipped."
            )
        )
