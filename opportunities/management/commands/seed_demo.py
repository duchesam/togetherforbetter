from datetime import timedelta
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from opportunities.models import Profile, Employer, Opportunity

class Command(BaseCommand):
    help = "Create clearly marked fictional opportunities for local evaluation; never real vacancies."
    @transaction.atomic
    def handle(self, *args, **options):
        from django.conf import settings
        if not settings.DEBUG:
            raise CommandError("Demo seeding is only supported in development mode.")
        samples = [
            ("demo_abay", "Abay Learning Initiative", "Communications & Community Intern", "internship", "Addis Ababa", "Communications", "ETB 5,000 monthly stipend", "Help turn meaningful work into stories that connect. Support community outreach, write short updates, and learn alongside our communications team.", "An interest in storytelling and community work. Clear written English or Amharic. Students and recent graduates are welcome."),
            ("demo_green", "Green Horizon Ethiopia", "Junior Program Assistant", "entry", "Addis Ababa", "Program operations", "ETB 12,000–16,000 / month", "Make a difference from day one. Help coordinate community programs, organize activities, and keep our team’s everyday work moving forward.", "A diploma or degree in a relevant field. Organizational skills, curiosity, and a willingness to learn. No prior professional experience required."),
            ("demo_seed", "Seedling Digital Studio", "Frontend Development Intern", "internship", "Remote, Ethiopia", "Technology", "ETB 6,000 monthly stipend", "Build useful digital experiences with a supportive team. Work on accessible websites, learn from code reviews, and grow your development skills.", "Basic HTML, CSS, and JavaScript skills. A personal or school project is welcome. Reliable access to a computer and internet."),
            ("demo_abay", "Abay Learning Initiative", "Graduate Finance Assistant", "entry", "Bahir Dar", "Finance", "ETB 10,000–14,000 / month", "Put your attention to detail to good use. Support basic bookkeeping, prepare financial records, and learn how nonprofit finances work.", "Recent accounting or finance graduate. Basic spreadsheet skills. Careful, reliable, and comfortable working with numbers."),
            ("demo_green", "Green Horizon Ethiopia", "Community Outreach Volunteer", "volunteer", "Hawassa", "Community development", "Unpaid · transport reimbursed", "Be part of a team bringing people together. Help organize local learning sessions and connect community members with useful resources.", "An interest in community service. Strong listening skills and local language knowledge. Available for six hours per week."),
            ("demo_seed", "Seedling Digital Studio", "Junior People & Culture Associate", "entry", "Addis Ababa", "People & operations", "ETB 11,000–15,000 / month", "Help create a welcoming workplace. Support hiring coordination, onboarding, and the small details that make a team feel connected.", "A relevant diploma or degree. Good communication and organization. Entry-level applicants are encouraged to apply."),
        ]
        for i, (username, name, title, kind, location, category, compensation, description, requirements) in enumerate(samples):
            user, created = User.objects.get_or_create(username=username, defaults={"email": f"{username}@example.invalid"})
            if created:
                user.set_unusable_password()
                user.save()
            Profile.objects.get_or_create(user=user, defaults={"full_name": name, "role": "employer"})
            employer, _ = Employer.objects.get_or_create(user=user, defaults={"name": name, "verified": True, "is_demo": True, "description": "This fictional organization is included for demonstration only. It is not recruiting."})
            if not employer.is_demo:
                raise CommandError("A demo username is already owned by a non-demo organization. No changes were saved.")
            Opportunity.objects.get_or_create(employer=employer, title=title, defaults={"kind": kind, "location": location, "category": category, "compensation": compensation, "description": description, "requirements": requirements, "published": True, "deadline": timezone.localdate() + timedelta(days=21+i*3)})
        self.stdout.write(self.style.SUCCESS("Demo data is ready: 3 fictional organizations and 6 illustrative opportunities. Existing data was preserved."))
