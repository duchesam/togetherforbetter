import re
import polib
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Compile project gettext catalogs without requiring GNU gettext binaries."

    def handle(self, *args, **options):
        paths = list((settings.BASE_DIR / "locale").glob("*/LC_MESSAGES/django.po"))
        if not paths:
            raise CommandError("No project translation catalogs found.")
        for source in paths:
            catalog = polib.pofile(str(source), check_for_duplicates=True)
            missing = [entry.msgid for entry in catalog if not entry.obsolete and (not entry.translated() or "fuzzy" in entry.flags)]
            if missing:
                raise CommandError(f"{source}: {len(missing)} missing or fuzzy translations")
            for entry in catalog:
                if "python-format" not in entry.flags:
                    continue
                placeholders = re.compile(r"%\([^)]+\)[sdi]|(?<!%)%[sdi]")
                expected = sorted(placeholders.findall(entry.msgid))
                variants = entry.msgstr_plural.values() if entry.msgid_plural else [entry.msgstr]
                if any(sorted(placeholders.findall(text)) != expected for text in variants):
                    raise CommandError(f"{source}: mismatched format placeholders in {entry.msgid!r}")
            catalog.save_as_mofile(str(source.with_suffix(".mo")))
            self.stdout.write(f"Compiled {len(catalog)} messages for {source.parent.parent.name}.")
