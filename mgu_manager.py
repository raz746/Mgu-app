import tkinter as tk
from tkinter import ttk, filedialog
import subprocess, json, pathlib, threading, queue, zipfile, tarfile, shutil, hashlib, datetime, io

class App:
 def __init__(self, root):
  self.root=root; root.title('BMW MGU App Manager v0.3 — Guided Workflow'); root.geometry('900x650')
  self.q=queue.Queue(); self.host=tk.StringVar(value='172.16.222.97'); self.port=tk.StringVar(value='22'); self.user=tk.StringVar(value='root'); self.key=tk.StringVar()
  f=ttk.Frame(root,padding=14); f.pack(fill='both',expand=True)
  ttk.Label(f,text='BMW MGU App Manager',font=('Segoe UI',18,'bold')).pack(anchor='w')
  ttk.Label(f,text='G87 / ID8 • SSH compatibility detection • No vehicle modifications').pack(anchor='w')
  for label,var in [('SSH host',self.host),('SSH port',self.port),('SSH username',self.user),('Private key path',self.key)]:
   r=ttk.Frame(f);r.pack(fill='x',pady=4);ttk.Label(r,text=label,width=20).pack(side='left');ttk.Entry(r,textvariable=var).pack(side='left',fill='x',expand=True)
   if var is self.key:ttk.Button(r,text='Browse',command=self.pick_key).pack(side='left')
  b=ttk.Frame(f);b.pack(fill='x',pady=8)
  ttk.Button(b,text='Check SSH & MGU',command=self.detect).pack(side='left',padx=3)
  ttk.Button(b,text='Inspect App Package',command=self.inspect).pack(side='left',padx=3)
  ttk.Button(b,text='Export Report',command=self.export).pack(side='left',padx=3)
  ttk.Button(b,text='Backup Coding',command=self.backup).pack(side='left',padx=3)
  ttk.Button(b,text='Workflow',command=self.workflow).pack(side='left',padx=3)
  self.out=tk.Text(f,wrap='word');self.out.pack(fill='both',expand=True);self.report={'app':'BMW MGU App Manager v0.3','mode':'read-only'}
  self.log('Ready. Requires Windows OpenSSH and an authorized SSH key. No install commands are executed.')
  self.root.after(100,self.poll)
 def log(self,s):self.q.put(s)
 def poll(self):
  try:
   while True:self.out.insert('end',self.q.get_nowait()+'\n');self.out.see('end')
  except queue.Empty:pass
  self.root.after(100,self.poll)
 def pick_key(self):
  p=filedialog.askopenfilename(title='Select SSH private key')
  if p:self.key.set(p)
 def detect(self):threading.Thread(target=self._detect,daemon=True).start()
 def _detect(self):
  host=self.host.get().strip();key=self.key.get().strip();user=self.user.get().strip()
  try:port=int(self.port.get());assert 1<=port<=65535
  except Exception:self.log('Invalid SSH port');return
  if not host or not user:self.log('Host and username are required');return
  if not shutil.which('ssh'):self.log('OpenSSH client not found. Install Windows OpenSSH Client.');return
  if not key or not pathlib.Path(key).is_file():self.log('Choose an existing SSH private key first.');return
  self.log('Checking SSH connectivity (read-only)...')
  args=['ssh','-F','none','-i',key,'-p',str(port),'-o','BatchMode=yes','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=yes','-o','NumberOfPasswordPrompts=0',f'{user}@{host}','uname -s; uname -m; cat /etc/os-release 2>/dev/null | head -n 6']
  try:
   p=subprocess.run(args,capture_output=True,text=True,timeout=18,stdin=subprocess.DEVNULL)
   result={'host':host,'port':port,'user':user,'ssh_returncode':p.returncode,'system_info':p.stdout[:4000],'error':p.stderr[:1500]}
   self.report['connection']=result
   self.log('SSH result: '+('connected' if p.returncode==0 else 'not verified'))
   if p.stdout:self.log(p.stdout[:4000])
   if p.stderr:self.log(p.stderr[:1500])
   self.log('ID8 app installation compatibility: UNVERIFIED. No writes performed.')
  except Exception as e:self.log('Connection check failed: '+str(e))
 def inspect(self):
  p=filedialog.askopenfilename(filetypes=[('MGU packages','*.mgu *.tgz *.tar.gz *.zip *.json'),('All files','*.*')])
  if not p:return
  info={'filename':pathlib.Path(p).name,'size_bytes':pathlib.Path(p).stat().st_size,'manifest_found':False,'id8_declared':False}
  try:
   raw=None
   if p.endswith('.json'):raw=pathlib.Path(p).read_bytes()
   elif zipfile.is_zipfile(p):
    with zipfile.ZipFile(p) as z:
     names=[n for n in z.namelist() if n.endswith(('package.json','mgu-repo.json','catalog.json'))]
     if names:raw=z.read(names[0]);info['manifest_path']=names[0]
   elif tarfile.is_tarfile(p):
    with tarfile.open(p,'r:*') as t:
     names=[m for m in t.getmembers() if m.isfile() and m.name.endswith(('package.json','mgu-repo.json','catalog.json'))]
     if names:raw=t.extractfile(names[0]).read();info['manifest_path']=names[0]
   if raw:
    data=json.loads(raw);info['manifest_found']=True;info['manifest']=data
    info['id8_declared']='ID8' in json.dumps(data.get('mguHmi',[]))
   self.report['package']=info
   self.log('Package inspected: '+info['filename']);self.log('Manifest: '+str(info['manifest_found'])+'; ID8 declared: '+str(info['id8_declared']))
   self.log('Manifest declaration alone does not prove safe or functional compatibility.')
  except Exception as e:self.log('Package inspection failed: '+str(e))
 def backup(self):
  from tkinter import simpledialog, messagebox
  messagebox.showinfo('Backup scope','This is an SSH file backup, not a verified full BMW coding/CAFD/NCD backup. Select only known coding/configuration files. No remote files will be changed.')
  remote=simpledialog.askstring('Remote file','Enter the exact absolute path of ONE known coding/configuration file on the MGU (no directories):')
  if not remote:return
  if not remote.startswith('/') or any(c in remote for c in '\\r\\n\\x00') or remote.endswith('/') or len(remote)>512:
   messagebox.showerror('Invalid path','Enter one absolute remote file path.');return
  if any(x in remote.lower() for x in ('/etc/shadow','/etc/ssh/','private_key','id_rsa','id_ed25519','password','credential')):
   messagebox.showerror('Protected path','Credential and SSH key files are excluded.');return
  dest=filedialog.askdirectory(title='Select local backup folder')
  if not dest:return
  threading.Thread(target=self._backup,args=(remote,dest),daemon=True).start()
 def _backup(self,remote,dest):
  import shlex
  host=self.host.get().strip();user=self.user.get().strip();key=self.key.get().strip()
  try:port=int(self.port.get());assert 1<=port<=65535
  except Exception:self.log('Invalid SSH port');return
  if not host or not user or not key or not pathlib.Path(key).is_file() or not shutil.which('ssh'):
   self.log('Backup requires valid SSH connection settings and OpenSSH.');return
  # SSH command arguments are quoted; no shell expansion of the requested path.
  cmd=['ssh','-F','none','-i',key,'-p',str(port),'-o','BatchMode=yes','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=yes','-o','NumberOfPasswordPrompts=0',f'{user}@{host}','cat -- '+shlex.quote(remote)]
  self.log('Reading one selected remote file; no remote writes...')
  try:
   p=subprocess.run(cmd,capture_output=True,timeout=90,stdin=subprocess.DEVNULL)
   if p.returncode!=0:
    self.log('Backup failed: '+p.stderr.decode('utf-8','replace')[:700]);return
   if len(p.stdout)>50*1024*1024:self.log('Backup file exceeds 50 MiB limit.');return
   stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
   folder=pathlib.Path(dest)/('MGU_backup_'+stamp);folder.mkdir(mode=0o700)
   filename=pathlib.PurePosixPath(remote).name
   output=folder/filename;output.write_bytes(p.stdout)
   digest=hashlib.sha256(p.stdout).hexdigest()
   manifest={'type':'selected SSH file backup, not full BMW coding backup','source_path':remote,'sha256':digest,'bytes':len(p.stdout),'created_local':stamp,'restore_supported':False}
   (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
   if hashlib.sha256(output.read_bytes()).hexdigest()!=digest:raise RuntimeError('Verification mismatch')
   self.log('Backup saved and SHA-256 verified: '+str(folder))
   self.log('Keep this folder private. No restore or vehicle modifications performed.')
  except Exception as e:self.log('Backup error: '+str(e))
 def workflow(self):
  from tkinter import messagebox
  w=tk.Toplevel(self.root);w.title('MGU Installation Workflow — v0.3');w.geometry('700x560')
  frame=ttk.Frame(w,padding=16);frame.pack(fill='both',expand=True)
  ttk.Label(frame,text='MGU App Installation — Guided Workflow',font=('Segoe UI',15,'bold')).pack(anchor='w')
  ttk.Label(frame,text='No installation or restoration occurs in this release.').pack(anchor='w',pady=4)
  stages=[
   ('1. Connect to MGU','Run SSH connectivity check','connect'),
   ('2. Identify firmware','Review detected OS and architecture; exact BMW firmware unverified','identify'),
   ('3. Backup coding','Back up selected known configuration files; full coding backup not verified','backup'),
   ('4. Verify backup','Validate local backup manifest and SHA-256 checksum','verify'),
   ('5. Select custom app','Inspect local package manifest','package'),
   ('6. Check compatibility','Review declared ID8 support; runtime compatibility unverified','compat'),
   ('7. Prepare installation','Generate a local readiness report; deployment disabled','prepare'),
   ('8. Install app','BLOCKED until verified deployment backend and ID8 support','install'),
   ('9. Post-install checks','BLOCKED until installation is implemented','post'),
   ('10. Restore backup','BLOCKED; restore requires verified full coding recovery method','restore')]
  status=tk.StringVar(value='Choose a workflow stage.')
  def action(kind):
   if kind=='connect':self.detect();status.set('SSH check started; see main window log.')
   elif kind=='identify':status.set('Run connection check; system information appears in report. BMW firmware remains unverified.')
   elif kind=='backup':self.backup();status.set('Selected-file backup started or cancelled.')
   elif kind=='verify':
    p=filedialog.askdirectory(title='Select MGU backup folder')
    if not p:return
    try:
     folder=pathlib.Path(p);manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
     name=pathlib.PurePosixPath(manifest['source_path']).name
     good=hashlib.sha256((folder/name).read_bytes()).hexdigest()==manifest['sha256']
     status.set('Backup SHA-256 '+('VERIFIED' if good else 'FAILED'))
     self.report['backup_verification']={'verified':good,'type':manifest.get('type','unknown')}
    except Exception as e:status.set('Backup verification failed: '+str(e))
   elif kind=='package':self.inspect();status.set('Package inspection opened.')
   elif kind=='compat':
    pkg=self.report.get('package',{})
    status.set('ID8 declared: '+str(pkg.get('id8_declared',False))+'; actual deployment compatibility UNVERIFIED.')
   elif kind=='prepare':
    self.report['installation_readiness']={'ssh_connected':self.report.get('connection',{}).get('ssh_returncode')==0,'package_inspected':bool(self.report.get('package')),'backup_verified':self.report.get('backup_verification',{}).get('verified',False),'deployment_supported':False,'ready_to_install':False}
    self.export();status.set('Readiness report exported. Installation remains blocked.')
   else:messagebox.showwarning('Unavailable','This operation is intentionally disabled until the MGU deployment/recovery method is verified.')
  for title,description,kind in stages:
   row=ttk.Frame(frame);row.pack(fill='x',pady=4)
   btn=ttk.Button(row,text=title,width=25,command=lambda k=kind:action(k))
   btn.pack(side='left',padx=(0,12))
   if kind in ('install','post','restore'):btn.state(['disabled'])
   ttk.Label(row,text=description,wraplength=420).pack(side='left',fill='x',expand=True)
  ttk.Separator(frame).pack(fill='x',pady=10)
  ttk.Label(frame,textvariable=status,wraplength=640).pack(anchor='w')
 def export(self):
  p=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')],initialfile='mgu_compatibility_report.json')
  if p:pathlib.Path(p).write_text(json.dumps(self.report,indent=2),encoding='utf-8');self.log('Report saved.')
if __name__=='__main__':
 root=tk.Tk();App(root);root.mainloop()
