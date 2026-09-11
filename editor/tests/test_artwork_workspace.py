import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from test_composite_project import build_dat, image_resource, palette_resource
from artwork_workspace import ArtworkWorkspace, read_package, import_package, validate_graphics
from composite_project import CompositeProject, CompositeProjectError
from prince_dat import DatArchive
from wall_profile import CONTRACT, FAMILIES, SLOTS, WallSettings, has_wall_bank
from wall_preview import render_recipe
from room_sets import ArchiveContext

def wall_dat():
    header=bytearray(palette_resource());header[0]=17
    return build_dat([(360,palette_resource()),(361,image_resource(4,2,0xb0,b'\x12\x34'*2)),
        (1600,bytes(header))]+[(i,image_resource(4,2,0xb0,b'\x12\x34'*2)) for i in range(1601,1618)])

class WallSettingsTests(unittest.TestCase):
    def test_exact_table_roundtrip_and_reserved_slots(self):
        settings=WallSettings();raw=settings.table_bytes()
        self.assertEqual(raw[4:8],b'\x88'*4)
        self.assertEqual(raw[24:28],b'\x22'*4)
        self.assertEqual(raw[:4],bytes(4))
        self.assertEqual(WallSettings.from_dict(settings.to_dict()).table_bytes(),raw)
        self.assertEqual(WallSettings.from_table(raw),settings)

    def test_reject_unsupported_or_dithered_patterns(self):
        for invalid in (-1,16,True,'2'):
            settings=WallSettings();settings.patterns[0x61]=invalid
            with self.assertRaises(ValueError):settings.table_bytes()
        raw=bytearray(WallSettings().table_bytes());raw[4]=0x89
        with self.assertRaises(ValueError):WallSettings.from_table(raw)

class ArtworkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/'source';self.folder.mkdir()
        for name in FAMILIES:(self.folder/name).write_bytes(wall_dat())
        self.workspace=ArtworkWorkspace.open_folder(self.folder)

    def test_profiles_active_legacy_and_reference_mapping(self):
        a=self.workspace.archives[FAMILIES[0]];p=self.workspace.projects[FAMILIES[0]]
        self.assertTrue(has_wall_bank(a));self.assertEqual(p.engine_profile,CONTRACT)
        for rid,used in ((1601,True),(361,False)):
            im=a.analysis_by_id(rid);e=p.edit_for_image(a,im.resource.index,im.image)
            self.assertEqual(e.enabled_phases,(0,));self.assertEqual(p.engine_usage_for_edit(e).used,used)
        p.edits[a.resource_by_id(1601).index].enabled_phases=(0,2)
        with self.assertRaises(CompositeProjectError):p.validate_phase_policy(p.edits[a.resource_by_id(1601).index])
        (self.folder/'VDUNGEON.DAT').write_bytes(build_dat([(361,image_resource(4,2,0xb0,b'\x12\x34'*2))]))
        context=ArchiveContext.discover(a)
        self.assertEqual(context.analysis_for_display_mode('vga',1601)[1].resource.resource_id,361)

    def test_unsaved_image_fill_export_import_and_determinism(self):
        a=self.workspace.archives[FAMILIES[0]];p=self.workspace.projects[FAMILIES[0]];im=a.analysis_by_id(1601)
        e=p.edit_for_image(a,im.resource.index,im.image);e.bits[2]^=1
        self.workspace.settings.patterns[0x61]=3
        first=Path(self.temp.name)/'first.zip';second=first.with_name('second.zip')
        self.workspace.export_zip(first);self.workspace.export_zip(second)
        self.assertEqual(first.read_bytes(),second.read_bytes())
        files,manifest,settings=read_package(first)
        self.assertEqual(settings.patterns[0x61],3)
        self.assertNotEqual(files['patched/CDUNGEON.DAT'],files['CDUNGEON.DAT'])
        reopened=import_package(first,Path(self.temp.name)/'imported')
        self.assertEqual(reopened.projects[FAMILIES[0]].edits[im.resource.index].bits,e.bits)
        reopened.export_zip(second);self.assertEqual(first.read_bytes(),second.read_bytes())
        with self.assertRaises(ValueError):import_package(first,self.folder)
        self.assertEqual((self.folder/FAMILIES[0]).read_bytes(),wall_dat())

    def test_reject_tamper_and_path_escape(self):
        path=Path(self.temp.name)/'art.zip';self.workspace.export_zip(path)
        with zipfile.ZipFile(path,'a') as z:z.writestr('../escape.txt','bad')
        with self.assertRaises(ValueError):read_package(path)
        self.workspace.export_zip(path)
        with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist()}
        files['WALLS.JSON']=files['WALLS.JSON'].replace(b'"carrier": 8',b'"carrier": 9')
        with zipfile.ZipFile(path,'w') as z:
            for n,raw in files.items():z.writestr(n,raw)
        with self.assertRaises(ValueError):read_package(path)

    def test_preserve_headers_and_geometry(self):
        a=self.workspace.archives[FAMILIES[0]]
        raw=build_dat([(r.resource_id,r.data if r.resource_id!=1600 else bytes(100)) for r in a.resources])
        with self.assertRaises(ValueError):validate_graphics(a,DatArchive.from_bytes(raw,FAMILIES[0]))

    def test_preview_uses_live_project_and_fill_settings(self):
        a=self.workspace.archives[FAMILIES[0]];p=self.workspace.projects[FAMILIES[0]];im=a.analysis_by_id(1601)
        commands=[['f',0,0,32,20,0x61],['i',FAMILIES[0],1601,0,0,16]]
        first=render_recipe(commands,self.workspace.archives,self.workspace.projects,self.workspace.settings)
        self.assertEqual(first.pick(0,0),(FAMILIES[0],1601))
        self.assertEqual(first.pick(20,10),('WALLS',0x61))
        self.assertIsNone(first.pick(-1,0))
        e=p.edit_for_image(a,im.resource.index,im.image);e.bits[2]^=1
        second=render_recipe(commands,self.workspace.archives,self.workspace.projects,self.workspace.settings)
        self.assertNotEqual(first.bits,second.bits)
        self.workspace.settings.patterns[0x61]=2
        third=render_recipe(commands,self.workspace.archives,self.workspace.projects,self.workspace.settings)
        self.assertNotEqual(second.bits[6400:6464],third.bits[6400:6464])

if __name__=='__main__':unittest.main()
