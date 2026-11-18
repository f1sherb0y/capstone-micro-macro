"""One local entry for the curated Capstone repository. Demos are offline only."""
import argparse,csv,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def show(value):print(json.dumps(value,ensure_ascii=False,indent=2))
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
def doctor():
 macro=ROOT/'vendor/gba'
 import pydantic,langchain_openai,numpy
 asset_errors=[]
 if (macro/'gba_construction_sim').is_dir():
  from integration.bootstrap import enable_gba_imports
  try:macro=enable_gba_imports()
  except (RuntimeError,OSError,ValueError,KeyError) as exc:asset_errors.append(str(exc))
 paths=['src','integration','prompts','skills','zwtnew','vendor/gba/data/processed/agent_database.sqlite','data/test_sources/casebank_enterprise_matched/simulation_input_projects.csv']
 missing=[p for p in paths if not (ROOT/p).exists()]
 database=ROOT/'vendor/gba/data/processed/agent_database.sqlite'
 if database.is_file():
  with database.open('rb') as f:header=f.read(16)
  if header!=b'SQLite format 3\x00':asset_errors.append('Macro database is not a SQLite file. Run git lfs install and git lfs pull.')
 show(dict(root=str(ROOT),python=sys.version.split()[0],macro=str(macro),missing=missing,asset_errors=asset_errors,independent_root=macro.exists() and macro.is_relative_to(ROOT),network_used=False,resource_note='Complete collaboration checkout requires Git LFS objects; credentials and temporary runs remain local.'))
 return int(bool(missing or asset_errors))
def data():
 result={}
 for p in (ROOT/'data/test_sources/casebank_enterprise_matched').glob('*.csv'):
  with p.open(encoding='utf-8-sig',newline='') as f:result[p.name]=sum(1 for _ in csv.DictReader(f))
 show(result)
def demo(kind, full=False):
 out=ROOT/'runs'/(kind+'-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True,exist_ok=False)
 guard=ROOT/'runs/_offline_guard';guard.mkdir(exist_ok=True)
 (guard/'sitecustomize.py').write_text('''import socket
_connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex
def guarded(original):
 def connect(self, address):
  # Windows asyncio uses a loopback socket pair for its event loop.
  if self.family == getattr(socket, "AF_UNIX", None):
   return original(self, address)
  if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
   return original(self, address)
  raise RuntimeError("Offline demo forbids external network")
 return connect
socket.socket.connect = guarded(_connect)
socket.socket.connect_ex = guarded(_connect_ex)
''',encoding='utf-8')
 env=os.environ.copy();env['PYTHONPATH']=str(guard)+os.pathsep+str(ROOT);env['PYTHONDONTWRITEBYTECODE']='1';env['CODEDEMO_USE_LOCAL_TEST_CLIENT']='1';env['PYTHONIOENCODING']='utf-8'
 def run(args):subprocess.run([sys.executable,*args],cwd=ROOT,env=env,check=True)
 if kind=='micro':run(['main.py','--case-id','CASE-0014','--profile','smoke','--output-dir',str(out)])
 else:
  config=read('config/origin_lifecycle_case.json')
  config_path=out/'demo-config.json'
  config_path.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
  run(['-m','integration.origin_lifecycle_case','--directory',str(out),'--build',str(config_path)])
  database=out/'agent_database.sqlite'
  shutil.copy2(ROOT/'vendor/gba/data/processed/agent_database.sqlite',database)
  args=['-m','scripts.offline_macro_demo',str(database),
        '--input',str(out/'input/macro-request.json'),'--output',str(out/'runtime'),
        '--offline','--input-format','gba_request','--macro-mode','gba_v1_module',
        '--allow-native-project-generation','--agent-client-factory','integration.native_routes:build_agent_client',
        '--agent-client-config',str(out/'input/native-host.json'),
        '--module-assembly-hook','integration.front_to_closeout_case:configure_assembly',
        '--module-assembly-config',str(out/'input/assembly-host.json')]
  if not full:args+=['--stop-after-tick','1','--checkpoint-out',str(out/'smoke-checkpoint.json')]
  (out/'command.json').write_text(json.dumps(args,ensure_ascii=False,indent=2),encoding='utf-8')
  run(args)
 show(dict(kind=kind,output=str(out),mode='offline',full_lifecycle=kind=='macro' and full,research_performance_result=False))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['doctor','data','results','micro-demo','macro-demo']);p.add_argument('--full',action='store_true',help='Run the full 48-tick macro lifecycle instead of the 1-tick environment check');a=p.parse_args()
 os.chdir(ROOT)
 if a.command=='doctor':return doctor()
 if a.command=='data':data()
 elif a.command=='results':
  items=read('results/index.json')
  for item in items:item['available']=(ROOT/item['path']).is_file()
  show(items)
 else:demo(a.command.split('-')[0],full=a.full)
 return 0
if __name__=='__main__':raise SystemExit(main())
