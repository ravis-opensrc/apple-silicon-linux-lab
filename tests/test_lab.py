import importlib.util
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

MOCK = r"""import json, os, pathlib, shutil, sys, tarfile, tempfile, time
args=sys.argv[1:]
name=pathlib.Path(sys.argv[0]).name
log=pathlib.Path(os.environ['MOCK_LOG'])
def record(value):
    with log.open('a') as stream: stream.write(json.dumps(value)+'\n')
record({'tool':name,'args':args,'pid':os.getpid()})
if name=='container' and args and args[0]=='run':
    def mount(target):
        for index,arg in enumerate(args):
            if arg=='--mount':
                fields=dict(part.split('=',1) for part in args[index+1].split(',') if '=' in part)
                if fields.get('target')==target:return pathlib.Path(fields['source'])
            if arg=='-v':
                source,destination=args[index+1].rsplit(':',1)
                if destination==target:return pathlib.Path(source)
    if os.environ.get('MOCK_BUILD_HANG')=='1':
        record({'build_waiting':True}); time.sleep(60)
    out=mount('/artifacts'); source=mount('/checkout')
    offset=args.index('linux-lab-build')
    mode=args[offset+2]; debug=args[offset+4]
    with tempfile.TemporaryDirectory() as temporary:
        tree=pathlib.Path(temporary)/'source'
        if mode=='working':shutil.copytree(source,tree,ignore=shutil.ignore_patterns('.git'))
        else:
            tree.mkdir()
            with tarfile.open(out/'source.tar') as archive:archive.extractall(tree,**({'filter':'data'} if hasattr(tarfile,'data_filter') else {}))
        (out/'Image').write_text((tree/'kernel/version').read_text())
        (out/'config').write_text((out/'requested.config').read_text())
        (out/'System.map').write_text('symbols')
        (out/'kernelrelease').write_text('test-kernel\n')
        if debug=='1':(out/'vmlinux').write_text('debug:'+ (out/'Image').read_text())
        with tarfile.open(out/'source.tar','w') as archive:
            for child in tree.iterdir():archive.add(child,arcname=child.name)
elif name=='qemu-img':pathlib.Path(args[-1]).touch()
elif name=='qemu-system-aarch64':
    image=pathlib.Path(args[args.index('-kernel')+1]); out=image.parent
    manifest=json.loads((out/'manifest.json').read_text())
    share=args[args.index('-virtfs')+1]
    assert 'path='+manifest['source']+',' in share
    assert (pathlib.Path(manifest['source'])/'kernel/version').read_text()==image.read_text()
    logfile=args[args.index('-chardev')+1].split('logfile=',1)[1]
    mode=os.environ.get('MOCK_VM_MODE','success')
    if mode=='hold':time.sleep(60)
    else:
        text='LINUX_LAB_SMOKE_STATUS=0\n'
        if mode!='no-kunit':text+='# Subtest: test\nok 1 test\n'
        if mode=='fail':text+='not ok 1 test\n'
        pathlib.Path(logfile).write_text(text)
elif name=='aarch64-elf-gdb':print(json.dumps(args))
"""


class ConfigTests(unittest.TestCase):
    def test_empty_values_and_spaced_list_are_preserved(self):
        spec=importlib.util.spec_from_file_location('config',ROOT/'scripts/load-config.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.yaml'
            path.write_text('kernel:\n  fragments:\n    - "a b.config"\nvm:\n  smoke_kunit_pattern: ""\n')
            value=module.load_simple_yaml(path)
            self.assertEqual(['a b.config'],value['kernel']['fragments'])
            self.assertEqual('',value['vm']['smoke_kunit_pattern'])


class InstallationTests(unittest.TestCase):
    def test_aliases_and_wrappers_work_from_quoted_spaced_path(self):
        with tempfile.TemporaryDirectory(prefix='lab install ') as directory:
            lab=Path(directory)/"repo $dollar's quoted path"
            (lab/'bin').mkdir(parents=True);(lab/'scripts').mkdir()
            shutil.copy(ROOT/'aliases.sh',lab/'aliases.sh')
            shutil.copy(ROOT/'scripts/install.sh',lab/'scripts/install.sh')
            shutil.copy(ROOT/'config.yaml.example',lab/'config.yaml.example')
            for name in ['setup-linux-lab','build-linux','launch-linux']:
                target=lab/'bin'/name
                target.write_text('#!/bin/sh\nprintf "argument=<%s>\\n" "$@"\n')
                target.chmod(0o755)
            result=subprocess.run(['bash','-O','expand_aliases','-c',
                                   'source "$1/aliases.sh"; eval \'launch-linux "two words"\'',
                                   'test',str(lab)],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            self.assertEqual('argument=<two words>\n',result.stdout)
            install_dir=Path(directory)/'installed wrappers'
            env=os.environ.copy();env['LINUX_LAB_BIN_DIR']=str(install_dir)
            subprocess.run([str(lab/'scripts/install.sh')],env=env,check=True,capture_output=True)
            result=subprocess.run([str(install_dir/'launch-linux'),'two words'],capture_output=True,text=True)
            self.assertEqual(0,result.returncode,result.stderr)
            self.assertEqual('argument=<two words>\n',result.stdout)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='linux lab ')
        self.base=Path(self.temp.name)
        self.source=self.base/'kernel checkout';(self.source/'kernel').mkdir(parents=True)
        (self.source/'kernel/version').write_text('A')
        self.git('init','-q');self.git('add','.');self.git('-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','A')
        self.commit_a=self.git('rev-parse','HEAD').strip()
        self.state=self.base/'state';(self.state/'ssh').mkdir(parents=True)
        (self.state/'alpine-3.24.4-lab-v6.raw').touch()
        # The launcher deliberately requires a nonempty base image.
        (self.state/'alpine-3.24.4-lab-v6.raw').write_bytes(b'base')
        self.tools=self.base/'tools';self.tools.mkdir()
        for tool in ['container','qemu-system-aarch64','qemu-img','aarch64-elf-gdb']:
            path=self.tools/tool;path.write_text('#!'+sys.executable+'\n'+MOCK);path.chmod(0o755)
        self.config=self.base/'config.yaml'
        self.config.write_text('kernel:\n  fragments:\n    - configs/base.config\nvm:\n  smoke_kunit_pattern: "# Subtest:"\n')
        self.env=os.environ.copy()
        # Do not let a developer's overrides leak into fixture tests.
        for key in list(self.env):
            if key.startswith('LINUX_'):self.env.pop(key)
        self.env.update(PATH=str(self.tools)+os.pathsep+self.env['PATH'],
                        LINUX_LAB_CONFIG=str(self.config),LINUX_SOURCE=str(self.source),
                        LINUX_LAB_STATE=str(self.state),LINUX_BUILD_JOBS='1',
                        MOCK_LOG=str(self.base/'mock.jsonl'),PYTHONDONTWRITEBYTECODE='1')
        self.processes=[]

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        self.temp.cleanup()

    def git(self,*args):
        return subprocess.check_output(['git','-C',str(self.source),*args],text=True)

    def run_cli(self,tool,*args,env=None,expect=0):
        result=subprocess.run([str(ROOT/'bin'/tool),*args],env=env or self.env,
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(expect,result.returncode,result.stdout+result.stderr)
        return result

    def build(self,*args):
        self.run_cli('build-linux',*args)
        return Path((self.state/'last-build').read_text().strip())

    def start_vm(self):
        env=self.env.copy();env['MOCK_VM_MODE']='hold'
        process=subprocess.Popen([str(ROOT/'bin/launch-linux'),'--gdb'],env=env,
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.processes.append(process)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if (self.state/'guest.json').exists():return process
            if process.poll() is not None:self.fail('VM failed to start')
            time.sleep(.02)
        self.fail('VM startup timed out')

    def test_absolute_fragment_with_spaces_is_staged(self):
        fragment=self.base/'extra configs'/'mm.config';fragment.parent.mkdir()
        fragment.write_text('CONFIG_TEST_WITH_SPACES=y\n')
        self.config.write_text('kernel:\n  fragments:\n    - configs/base.config\n    - "'+str(fragment)+'"\n')
        artifact=self.build()
        self.assertIn('CONFIG_TEST_WITH_SPACES=y',(artifact/'requested.config').read_text())

    def test_named_ref_uses_matching_snapshot_not_current_checkout(self):
        (self.source/'kernel/version').write_text('B')
        self.git('add','.');self.git('-c','user.name=Test','-c','user.email=test@example.test','commit','-qm','B')
        artifact=self.build(self.commit_a)
        manifest=json.loads((artifact/'manifest.json').read_text())
        self.assertEqual('B',(self.source/'kernel/version').read_text())
        self.assertEqual('A',(Path(manifest['source'])/'kernel/version').read_text())
        self.run_cli('launch-linux',self.commit_a,'--smoke')

    def test_working_build_includes_edits_and_older_generation_is_unchanged(self):
        (self.source/'kernel/version').write_text('uncommitted A')
        first=self.build()
        (self.source/'kernel/version').write_text('uncommitted B')
        second=self.build()
        self.assertNotEqual(first,second)
        self.assertEqual('uncommitted A',(first/'Image').read_text())
        self.assertEqual('uncommitted B',(second/'Image').read_text())

    def test_attach_uses_running_generation_after_new_build(self):
        first=self.build('--debug');process=self.start_vm()
        (self.source/'kernel/version').write_text('B')
        second=self.build('--debug')
        self.assertNotEqual(first,second)
        result=self.run_cli('launch-linux','--attach-gdb')
        self.assertIn(str(first/'vmlinux'),result.stdout)
        self.assertNotIn(str(second/'vmlinux'),result.stdout)
        source=json.loads((first/'manifest.json').read_text())['source']
        self.assertIn(source,result.stdout)
        process.terminate();self.assertEqual(143,process.wait(timeout=20))
        self.assertFalse((self.state/'guest.lock').exists())
        self.assertFalse((self.state/'guest.json').exists())

    def test_empty_pattern_allows_boot_without_kunit_output(self):
        self.config.write_text('vm:\n  smoke_kunit_pattern: ""\n')
        self.build();env=self.env.copy();env['MOCK_VM_MODE']='no-kunit'
        self.run_cli('launch-linux','--smoke',env=env)

    def test_smoke_rejects_failed_kunit(self):
        self.build();env=self.env.copy();env['MOCK_VM_MODE']='fail'
        self.run_cli('launch-linux','--smoke',env=env,expect=1)
        self.assertFalse((self.state/'guest.lock').exists())

    def test_smoke_timeout_kills_vm_and_releases_lock(self):
        self.build();env=self.env.copy();env.update(MOCK_VM_MODE='hold',LINUX_SMOKE_TIMEOUT='1')
        self.run_cli('launch-linux','--smoke',env=env,expect=124)
        self.assertFalse((self.state/'guest.lock').exists())
        self.assertFalse((self.state/'guest.json').exists())

    def test_term_stops_container_before_unlocking(self):
        env=self.env.copy();env['MOCK_BUILD_HANG']='1'
        process=subprocess.Popen([str(ROOT/'bin/build-linux')],env=env,
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.processes.append(process)
        log=Path(env['MOCK_LOG']);deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if log.exists() and 'build_waiting' in log.read_text():break
            time.sleep(.02)
        else:self.fail('Build did not enter container')
        process.terminate();self.assertEqual(143,process.wait(timeout=20))
        self.assertIn('"stop"',log.read_text())
        self.assertFalse((self.state/'build.lock').exists())
        self.assertFalse((self.state/'last-build').exists())

    def test_snapshot_directory_inside_checkout_is_rejected(self):
        self.env['LINUX_LAB_SNAPSHOTS']=str(self.source/'nested snapshots')
        result=self.run_cli('build-linux',expect=1)
        self.assertIn('outside the kernel checkout',result.stderr)
        self.assertFalse((self.source/'nested snapshots').exists())

    def test_missing_explicit_config_fails_before_build(self):
        self.env['LINUX_LAB_CONFIG']=str(self.base/'missing.yaml')
        result=self.run_cli('build-linux',expect=1)
        self.assertIn('Configuration file not found',result.stderr)
        self.assertFalse(Path(self.env['MOCK_LOG']).exists())

    def test_attach_without_guest_refuses_stale_symbols(self):
        self.build('--debug')
        self.run_cli('launch-linux','--attach-gdb',expect=1)


if __name__=='__main__':unittest.main()
