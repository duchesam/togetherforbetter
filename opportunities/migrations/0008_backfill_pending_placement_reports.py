from django.db import migrations


def backfill(apps, schema_editor):
    Application = apps.get_model('opportunities', 'Application')
    Report = apps.get_model('opportunities', 'PlacementReport')
    alias = schema_editor.connection.alias
    hires = Application.objects.using(alias).filter(status='hired').values_list('pk','updated_at','opportunity__employer__user_id')
    for pk, updated_at, reporter_id in hires.iterator():
        Report.objects.using(alias).get_or_create(application_id=pk, superseded_at__isnull=True, defaults={'reported_at':updated_at,'reported_by_id':reporter_id,'response':'pending'})


class Migration(migrations.Migration):
    dependencies = [('opportunities','0007_alter_application_status_alter_notification_kind_and_more')]
    operations = [migrations.RunPython(backfill,migrations.RunPython.noop)]
