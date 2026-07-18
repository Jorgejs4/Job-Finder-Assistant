#!/usr/bin/env python3
"""
Unit tests para la lógica core del Job Scraper Assistant.
Ejecutar: pytest tests/test_unit.py -v
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("DESIRED_LOCATIONS", "Remoto")
os.environ.setdefault("MOCK_GEMINI", "true")
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")
os.environ.setdefault("GEMINI_API_KEYS", "test-key-not-real")
os.environ.setdefault("NOTION_TOKEN", "test-token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-db-id")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


class TestKeywordFilter:
    """Tests para el filtro de keywords no-tech."""

    def test_tech_jobs_pass(self):
        tech_titles = [
            "Desarrollador Python Junior",
            "Software Engineer",
            "Full Stack Developer",
            "Frontend Engineer React",
            "Backend Developer Java",
            "DevOps Engineer",
            "QA Engineer",
        ]
        for title in tech_titles:
            combined = title.lower()
            is_blocked = any(kw in combined for kw in config.NON_TECH_KEYWORDS)
            assert not is_blocked, f"Tech job '{title}' should NOT be blocked"

    def test_non_tech_jobs_blocked(self):
        non_tech_titles = [
            "Operario de limpieza",
            "Camarero de hostelería",
            "CAJERO de supermercado",
            "Reponedor de estanterías",
            "Auxiliar Administrativo",
            "Virtual Executive Assistant",
            "Community Manager Digital",
            "Conductor de autobús",
            "Personal de seguridad",
        ]
        for title in non_tech_titles:
            combined = title.lower()
            is_blocked = any(kw in combined for kw in config.NON_TECH_KEYWORDS)
            assert is_blocked, f"Non-tech job '{title}' should be blocked"


class TestConfig:
    """Tests para la configuración."""

    def test_role_translations_exist(self):
        assert len(config.ROLE_TRANSLATIONS) > 0
        assert "desarrollador backend" in config.ROLE_TRANSLATIONS
        assert config.ROLE_TRANSLATIONS["desarrollador backend"] == "backend developer"

    def test_application_statuses(self):
        expected = ["Nuevo", "Revisado", "Interesado", "Aplicado", "Entrevista", "Oferta", "Rechazado"]
        assert config.APPLICATION_STATUSES == expected

    def test_fuzzy_threshold_default(self):
        assert config.FUZZY_MATCH_THRESHOLD == 85

    def test_en_scrapers(self):
        assert "LinkedInScraper" in config.EN_SCRAPERS
        assert "RemoteOKScraper" not in config.EN_SCRAPERS
        assert "InfoJobsScraper" not in config.EN_SCRAPERS

    def test_location_map_keys(self):
        assert "sevilla" in config.LOCATION_MAP
        assert "madrid" in config.LOCATION_MAP
        assert "remoto" in config.LOCATION_MAP
        assert "linkedin" in config.LOCATION_MAP["sevilla"]

    def test_get_location_for_known(self):
        loc = config.get_location_for("linkedin", "sevilla")
        assert loc == "Sevilla, Andalucía, España"

    def test_get_location_for_unknown(self):
        loc = config.get_location_for("unknown_scraper", "murcia")
        assert loc == "Murcia"


class TestGeminiModels:
    """Tests para los modelos de Gemini."""

    def test_offer_match_fields(self):
        from utils.gemini_client import OfferMatch
        fields = list(OfferMatch.model_fields.keys())
        assert "match_score" in fields
        assert "tech_stack" in fields
        assert "cover_letter" in fields
        assert "cv_summary" in fields
        assert "cv_skills" in fields

    def test_profile_analysis_fields(self):
        from utils.gemini_client import ProfileAnalysis
        fields = list(ProfileAnalysis.model_fields.keys())
        assert "recommended_roles" in fields
        assert "key_skills" in fields
        assert "years_of_experience" in fields


class TestGeminiMock:
    """Tests para el mock de Gemini."""

    def test_mock_match_offer(self):
        from utils.gemini_client import GeminiClient
        os.environ["MOCK_GEMINI"] = "true"
        gemini = GeminiClient()
        result = gemini.match_offer(
            cv_text="Python developer with 2 years experience",
            offer_title="Desarrollador Python",
            offer_description="Buscamos python developer con Django",
            experience_hint=2,
        )
        assert result.match_score > 0
        assert result.match_score <= 100
        assert result.work_mode in ["Presencial", "Remoto", "Híbrido"]
        assert result.estimated_salary > 0
        assert len(result.cover_letter) > 0
        assert len(result.cv_skills) > 0

    def test_mock_analyze_cv(self):
        from utils.gemini_client import GeminiClient
        os.environ["MOCK_GEMINI"] = "true"
        gemini = GeminiClient()
        result = gemini.analyze_cv("Python developer with Docker experience")
        assert len(result.recommended_roles) > 0
        assert len(result.key_skills) > 0
        assert result.years_of_experience >= 0


class TestCVGenerator:
    """Tests para el generador de CVs."""

    def test_generate_from_data(self):
        from utils.cv_generator import CVGenerator
        cv_gen = CVGenerator()
        cv_content = {
            "name": "Test User",
            "contact": "test@email.com",
            "summary": "Test summary",
            "experience": [{"role": "Dev", "company": "Test", "period": "2024", "description": ["Work done"]}],
            "education": [],
            "skills": {"Backend": ["Python", "Docker"]},
            "projects": [],
        }
        html_path, pdf_path, cl_pdf_path = cv_gen.generate_from_data(cv_content, "Test Job", "Test Co")
        assert pdf_path is not None
        assert os.path.exists(pdf_path)
        assert os.path.getsize(pdf_path) > 0
        if html_path and os.path.exists(html_path):
            os.remove(html_path)
        os.remove(pdf_path)


class TestResultsManager:
    """Tests para el ResultsManager."""

    def test_save_and_load(self):
        from utils.results import ResultsManager
        rm = ResultsManager()
        rm.set_total_added(5)
        rm.set_analyzed_count(10)
        rm.record_scraper_result("TestScraper", [{"title": "test"}])
        rm.save()

        assert rm.run_data["_total_added"] == 5
        assert rm.run_data["_analyzed_count"] == 10
        stats = rm.get_scraper_stats()
        assert "TestScraper" in stats
        assert stats["TestScraper"]["found"] == 1


class TestFeedbackManager:
    """Tests para el gestor de feedback de CVs."""

    def test_save_and_retrieve(self):
        from utils.feedback_manager import FeedbackManager
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = FeedbackManager(results_dir=tmpdir)
            fm.save_feedback("Test Job", "Test Co", "Más detalle en Spring Boot")
            pending = fm.get_pending()
            assert len(pending) == 1
            assert pending[0]["title"] == "Test Job"
            assert pending[0]["feedback"] == "Más detalle en Spring Boot"

    def test_mark_done(self):
        from utils.feedback_manager import FeedbackManager
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = FeedbackManager(results_dir=tmpdir)
            fm.save_feedback("Job A", "Co A", "feedback text")
            job_id = fm.make_job_id("Job A", "Co A")
            fm.mark_done(job_id)
            assert fm.count_pending() == 0
            assert len(fm._data["completed"]) == 1

    def test_has_pending(self):
        from utils.feedback_manager import FeedbackManager
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = FeedbackManager(results_dir=tmpdir)
            assert not fm.has_pending("Job A", "Co A")
            fm.save_feedback("Job A", "Co A", "test")
            assert fm.has_pending("Job A", "Co A")


class TestCVContentModel:
    """Tests para el modelo CVContent de Gemini."""

    def test_cv_content_fields(self):
        from utils.gemini_client import CVContent
        cv = CVContent(
            name="Test",
            contact="test@email.com",
            summary="Backend Developer con 2 años de experiencia.",
            experience=[{"role": "Dev", "company": "Co", "period": "2024", "description": ["Bullet 1"]}],
            education=[{"degree": "DAM", "institution": "IES", "year": "2022"}],
            skills={"Backend": ["Python"], "Cloud": ["AWS"]},
            projects=[{"name": "Proj", "description": "Desc"}],
        )
        assert cv.name == "Test"
        assert isinstance(cv.skills, dict)
        assert "Backend" in cv.skills
