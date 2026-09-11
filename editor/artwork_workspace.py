"""Complete graphics workspace and deterministic editor/build exchange ZIP."""
# SPDX-License-Identifier: GPL-2.0-or-later
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile
import zlib
from prince_dat import DatArchive
from composite_project import CompositeProject, rebuild_dat, replacement_contents
from wall_profile import CONTRACT, CONTRACTS, OVERLAY_CONTRACT, FAMILIES, WallSettings, has_wall_bank, wall_contract

KIND='prince-composite-artwork'
GRAPHICS=frozenset(('CDUNGEON.DAT','CPALACE.DAT','KID.DAT','GUARD.DAT','FAT.DAT',
    'SKEL.DAT','VIZIER.DAT','SHADOW.DAT','PRINCE.DAT','PV.DAT','TITLE.DAT','ORIENT.DAT'))

def json_bytes(value):return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode('utf-8')
def sha(raw):return hashlib.sha256(raw).hexdigest()

def validate_graphics(base, updated):
    """Accept geometry-preserving image edits; preserve tables and binary code/data."""
    if [r.resource_id for r in base.resources]!=[r.resource_id for r in updated.resources]:
        raise ValueError(f'{base.path.name}: resource IDs/order changed.')
    for old,new in zip(base.analyses,updated.analyses):
        if old.resource.data==new.resource.data:continue
        if base.path.name.upper() not in GRAPHICS or old.image is None or new.image is None:
            raise ValueError(f'{base.path.name}/{old.resource.resource_id}: protected data changed.')
        if (old.image.width,old.image.height,old.image.bits)!=(new.image.width,new.image.height,new.image.bits):
            raise ValueError(f'{base.path.name}/{old.resource.resource_id}: image dimensions/depth changed.')
    if not all(r.checksum_ok for r in updated.resources):raise ValueError('Invalid DAT checksum.')

class ArtworkWorkspace:
    def __init__(self,folder,archives,projects,settings,recipes):
        self.folder=Path(folder);self.archives=archives;self.projects=projects
        self.settings=settings;self.recipes=recipes
        self.dirty=False

    @classmethod
    def open_folder(cls,folder):
        folder=Path(folder)
        archives={p.name.upper():DatArchive.open(p) for p in sorted(folder.iterdir())
            if p.suffix.upper()=='.DAT' and p.name.upper() not in ('CONFIG.DAT','SETUP.DAT')}
        if not all(n in archives and has_wall_bank(archives[n]) for n in FAMILIES):
            missing=', '.join(n for n in FAMILIES if n not in archives or not has_wall_bank(archives[n]))
            raise ValueError(f'{missing}: missing the expanded wall table (resource 1600). A standard artwork DAT does not contain the experimental overlays. Open the prepared V24Z game folder or import its complete artwork ZIP.')
        projects={n:CompositeProject.for_archive(a) for n,a in archives.items() if n in GRAPHICS}
        for n in projects:
            p=folder/'projects'/f'{n}.json'
            if p.is_file():
                projects[n]=CompositeProject.load(p);projects[n].verify_archive(archives[n])
        settings_path=folder/('WALLS.JSON' if (folder/'WALLS.JSON').is_file() else 'WALLS.JSN')
        recipes_path=folder/('PREVIEWS.JSON' if (folder/'PREVIEWS.JSON').is_file() else 'PREVIEW.JSN')
        contract=wall_contract(archives[FAMILIES[1]])
        settings=WallSettings.from_dict(json.loads(settings_path.read_text())) if settings_path.is_file() else (
            WallSettings.overlays() if contract==OVERLAY_CONTRACT else WallSettings())
        if settings.engine_contract!=contract:raise ValueError('Wall settings do not match the DAT layout.')
        recipes=json.loads(recipes_path.read_text()) if recipes_path.is_file() else None
        if recipes is None and (folder/'PREVIEW.CPR').is_file():
            packed=(folder/'PREVIEW.CPR').read_bytes()
            decoder=zlib.decompressobj();raw=decoder.decompress(packed,16*1024*1024+1)
            if len(raw)>16*1024*1024 or not decoder.eof or decoder.unused_data:raise ValueError('Invalid or oversized room preview data.')
            recipes=json.loads(raw)
        if recipes and recipes.get('engine_contract')!=contract:raise ValueError('Incompatible preview recipes.')
        return cls(folder,archives,projects,settings,recipes)

    def bind(self,archive,project):
        name=archive.path.name.upper()
        if name not in self.projects:raise ValueError('This archive is not part of the graphics workspace.')
        project.verify_archive(archive)
        if archive.data!=self.archives[name].data:raise ValueError('The editor and workspace have different source DATs.')
        self.projects[name]=project

    def members(self):
        files={};baselines={}
        for name,a in sorted(self.archives.items()):
            files[name]=a.data;baselines[name]=sha(a.data)
            p=self.projects.get(name)
            edited=rebuild_dat(a,replacement_contents(a,p)) if p else a.data
            validate_graphics(a,DatArchive.from_bytes(edited,name))
            files['patched/'+name]=edited
            if p:
                obj=p.to_dict();obj.pop('saved_utc',None)
                files[f'projects/{name}.json']=json_bytes(obj)
        files['WALLS.JSON']=json_bytes(self.settings.to_dict())
        if self.recipes:files['PREVIEWS.JSON']=json_bytes(self.recipes)
        manifest={'kind':KIND,'schema':1,'engine_contract':self.settings.engine_contract,'art_credit':'VileR',
            'source_hashes':baselines,'files':{n:{'size':len(raw),'sha256':sha(raw)} for n,raw in sorted(files.items())}}
        files['ARTWORK.JSON']=json_bytes(manifest)
        return files

    def export_zip(self,path):
        path=Path(path);files=self.members();path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix='.artwork-',suffix='.zip',dir=path.parent);os.close(fd)
        try:
            with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
                for name,raw in sorted(files.items()):
                    info=zipfile.ZipInfo(name,(2026,9,9,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
                    z.writestr(info,raw)
            read_package(tmp)
            os.replace(tmp,path)
        finally:
            if Path(tmp).exists():Path(tmp).unlink()
        self.dirty=False
        return path

def read_package(path):
    """Read and fully validate a package before extraction or build consumption."""
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or len(names)>256:raise ValueError('Duplicate or excessive package members.')
        if sum(i.file_size for i in z.infolist())>64*1024*1024:raise ValueError('Artwork package exceeds 64 MiB.')
        for n in names:
            if n not in ('ARTWORK.JSON','WALLS.JSON','PREVIEWS.JSON') and not re.fullmatch(r'(?:(?:patched/)?[A-Z0-9_]{1,8}\.DAT|projects/[A-Z0-9_]{1,8}\.DAT\.json)',n):
                raise ValueError(f'Unexpected package path: {n}')
        files={n:z.read(n) for n in names}
    manifest=json.loads(files['ARTWORK.JSON'])
    if (manifest.get('kind'),manifest.get('schema'))!=(KIND,1) or manifest.get('engine_contract') not in CONTRACTS:raise ValueError('Unsupported artwork package.')
    if set(manifest['files'])!=set(files)-{'ARTWORK.JSON'}:raise ValueError('Manifest membership mismatch.')
    for n,meta in manifest['files'].items():
        if meta!={'size':len(files[n]),'sha256':sha(files[n])}:raise ValueError(f'Artwork checksum mismatch: {n}')
    sources={n:DatArchive.from_bytes(raw,n) for n,raw in files.items() if '/' not in n and n.endswith('.DAT')}
    if set(manifest['source_hashes'])!=set(sources):raise ValueError('Source inventory mismatch.')
    if not all(n in sources and has_wall_bank(sources[n]) for n in FAMILIES):raise ValueError('Missing expanded wall assets.')
    expected={n for n in files if n.startswith('patched/')}
    if expected!={'patched/'+n for n in sources}:raise ValueError('Patched asset inventory mismatch.')
    for n,a in sources.items():
        if sha(a.data)!=manifest['source_hashes'][n]:raise ValueError('Source hash mismatch.')
        updated=DatArchive.from_bytes(files['patched/'+n],n);validate_graphics(a,updated)
        key=f'projects/{n}.json'
        if key in files:
            if n not in GRAPHICS:raise ValueError('Project targets non-graphics data.')
            p=CompositeProject.from_dict(json.loads(files[key]));p.verify_archive(a)
            if rebuild_dat(a,replacement_contents(a,p))!=updated.data:raise ValueError('Project and patched DAT disagree.')
        elif a.data!=updated.data:raise ValueError('Edited DAT is missing its project.')
    settings=WallSettings.from_dict(json.loads(files['WALLS.JSON']))
    if not settings.engine_contract==manifest['engine_contract']==wall_contract(sources[FAMILIES[1]]):
        raise ValueError('Artwork settings, DAT layout and engine contract disagree.')
    if 'PREVIEWS.JSON' in files and json.loads(files['PREVIEWS.JSON']).get('engine_contract')!=settings.engine_contract:
        raise ValueError('Incompatible preview recipes.')
    return files,manifest,settings

def import_package(path,destination):
    files,_,_=read_package(path)
    destination=Path(destination)
    if destination.exists():raise ValueError('Choose a new workspace folder; existing files are protected.')
    destination.mkdir(parents=True)
    for name,raw in files.items():
        p=destination/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    return ArtworkWorkspace.open_folder(destination)
