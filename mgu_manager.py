import tkinter as tk
from tkinter import ttk, filedialog
import subprocess, json, pathlib, threading, queue, zipfile, tarfile, shutil, hashlib, datetime, io

class App:
 def __init__(self, root):
  self.root=root; root.title('BMW MGU App Manager v0.2 — Read-only'); root.geometry('780x600')
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
  self.out=tk.Text(f,wrap='word');self.out.pack(fill='both',expand=True);self.report={'app':'BMW MGU App Manager v0.2','mode':'read-only'}
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
 def export(self):
  p=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')],initialfile='mgu_compatibility_report.json')
  if p:pathlib.Path(p).write_text(json.dumps(self.report,indent=2),encoding='utf-8');self.log('Report saved.')
if __name__=='__main__':
 root=tk.Tk();App(root);root.mainloop()
