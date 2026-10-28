"""Run an isolated production smoke test using only synthetic, disposable data."""
import os,re,secrets,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='together-production-drill-') as temporary:
 private=Path(temporary)/'private';private.mkdir(mode=0o700)
 public=Path(temporary)/'static'
 env=os.environ|{'DJANGO_DEBUG':'0','DJANGO_SECRET_KEY':secrets.token_urlsafe(64),'PUBLIC_SITE_URL':'https://pilot.example.org','DJANGO_ALLOWED_HOSTS':'pilot.example.org','DJANGO_DATA_DIR':str(private),'DJANGO_STATIC_ROOT':str(public),'DJANGO_TRUST_PROXY_SSL_HEADER':'1','DJANGO_CSRF_TRUSTED_ORIGINS':'https://pilot.example.org','OPENAI_API_KEY':'','EMAIL_BACKEND':'django.core.mail.backends.dummy.EmailBackend'}
 for args in [['migrate','--noinput'],['collectstatic','--noinput'],['check','--deploy']]:
  result=subprocess.run([sys.executable,'manage.py',*args],cwd=root,env=env,capture_output=True,text=True,check=True)
  if args[0]=='check':print(result.stdout+result.stderr)
 # Exercise a real Django recovery before starting any writer processes.
 fixture = """
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.utils import timezone
from datetime import timedelta
from opportunities.models import Profile, Employer, Opportunity, Application, ResumeDraft
from pypdf import PdfWriter
from io import BytesIO
owner=User.objects.create_user('recovery-demo-employer')
candidate=User.objects.create_user('recovery-demo-applicant')
Profile.objects.create(user=owner,role='employer',full_name='Synthetic employer',email_notifications=False)
profile=Profile.objects.create(user=candidate,role='seeker',full_name='Synthetic applicant',email_notifications=False)
buffer=BytesIO(); writer=PdfWriter(); writer.add_blank_page(width=300,height=400); writer.write(buffer)
profile.cv.save('example.pdf',ContentFile(buffer.getvalue()))
employer=Employer.objects.create(user=owner,name='Synthetic recovery organization',is_demo=True)
job=Opportunity.objects.create(employer=employer,title='Synthetic recovery role',kind='entry',deadline=timezone.localdate()+timedelta(days=30))
Application.objects.create(opportunity=job,applicant=candidate,cover_letter='Synthetic recovery message')
ResumeDraft.objects.create(user=candidate,full_name='Synthetic applicant',summary='Synthetic recovery draft')
"""
 subprocess.run([sys.executable,'manage.py','shell','-c',fixture],cwd=root,env=env,stdout=subprocess.DEVNULL,check=True)
 archive=Path(temporary)/'backup'/'snapshot.tar.gz'
 restored=Path(temporary)/'restored'
 for args in [['backup_pilot','--output',str(archive),'--offline'],['restore_pilot','--archive',str(archive),'--destination',str(restored)]]:
  subprocess.run([sys.executable,'manage.py',*args],cwd=root,env=env,stdout=subprocess.DEVNULL,check=True)
 env['DJANGO_DATA_DIR']=str(restored)
 verify="""
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from opportunities.models import Application,ResumeDraft
candidate=User.objects.get(username='recovery-demo-applicant')
assert Application.objects.get(applicant=candidate).cover_letter=='Synthetic recovery message'
assert ResumeDraft.objects.get(user=candidate).summary=='Synthetic recovery draft'
client=Client();client.force_login(candidate)
cv=client.get(reverse('download_cv',args=[candidate.profile.pk]),secure=True,HTTP_HOST='pilot.example.org')
assert cv.status_code==200 and b''.join(cv.streaming_content).startswith(b'%PDF-')
resume=client.get(reverse('resume_download'),secure=True,HTTP_HOST='pilot.example.org')
assert resume.status_code==200 and resume.content.startswith(b'%PDF-')
"""
 subprocess.run([sys.executable,'manage.py','shell','-c',verify],cwd=root,env=env,stdout=subprocess.DEVNULL,check=True)
 print('Recovery drill passed: Django accounts, applications, private CV download and resume PDF export restored in isolation.')
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 process=subprocess.Popen([sys.executable,'-m','gunicorn','--config','deploy/gunicorn.conf.py','--bind',f'127.0.0.1:{port}','config.wsgi:application'],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 def get(path):
  return urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers={'Host':'pilot.example.org','X-Forwarded-Proto':'https'}),timeout=10)
 try:
  for attempt in range(100):
   try:
    response=get('/login/');break
   except (OSError,urllib.error.URLError):time.sleep(.1)
  else:raise RuntimeError('Production WSGI did not start')
  html=response.read().decode()
  assert response.status==200
  assert response.headers.get('Strict-Transport-Security')=='max-age=3600'
  assert 'Secure' in response.headers.get('Set-Cookie','')
  static=re.search(r'<script src="([^"]+)"',html).group(1)
  assert get(static).status==200
  try:get('/private-media/cvs/not-public.pdf')
  except urllib.error.HTTPError as error:assert error.code==404
  else:raise RuntimeError('Private files route unexpectedly public')
  print('Production smoke passed: fresh migrations, collected hashed static files, Gunicorn WSGI, secure cookies, HSTS and private file isolation.')
 finally:
  process.terminate();process.wait(timeout=10)
