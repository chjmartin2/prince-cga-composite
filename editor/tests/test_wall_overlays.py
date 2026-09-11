import json
from pathlib import Path
import tempfile
import unittest
from test_artwork_workspace import wall_dat
from test_composite_project import build_dat, image_resource, palette_resource
from artwork_workspace import ArtworkWorkspace, read_package, import_package
from prince_dat import DatArchive
from composite_project import CompositeProject, CompositeProjectError
from wall_profile import FAMILIES, OVERLAY_CONTRACT, WallSettings, wall_components
from wall_preview import render_recipe, without_overlays, overlay_inspector

class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)/'source';self.folder.mkdir()
        (self.folder/FAMILIES[0]).write_bytes(wall_dat())
        old=DatArchive.from_bytes(wall_dat(),FAMILIES[1])
        resources={r.resource_id:r.data for r in old.resources}
        header=bytearray(resources[1600]);header[0]=19;resources[1600]=bytes(header)
        resources[1618]=resources[1619]=resources[1601]
        # Zero is transparent; index 4 is an opaque source pixel (even if black).
        resources[1603]=image_resource(4,2,0xb0,b'\x04\x10'*2)
        (self.folder/FAMILIES[1]).write_bytes(build_dat(sorted(resources.items())))
        self.ws=ArtworkWorkspace.open_folder(self.folder)

    def test_overlay_contract_rejects_color_fills_and_roundtrips(self):
        self.assertEqual(self.ws.settings.engine_contract,OVERLAY_CONTRACT)
        self.assertEqual(WallSettings.from_dict(self.ws.settings.to_dict()),self.ws.settings)
        with self.assertRaises(ValueError):self.ws.settings.table_bytes()
        bad=self.ws.settings.to_dict();bad['fills']={'61':{'carrier':8}}
        with self.assertRaises(ValueError):WallSettings.from_dict(bad)

    def test_new_bases_are_editable_p0_and_preserved_in_exchange(self):
        a=self.ws.archives[FAMILIES[1]];p=self.ws.projects[FAMILIES[1]]
        im=a.analysis_by_id(1619);e=p.edit_for_image(a,im.resource.index,im.image)
        self.assertEqual(p.engine_profile,OVERLAY_CONTRACT)
        self.assertTrue(p.engine_usage_for_edit(e).used)
        self.assertEqual(e.enabled_phases,(0,));e.bits[4]^=1
        first=Path(self.tmp.name)/'first.zip';second=first.with_name('second.zip')
        self.ws.export_zip(first)
        files,manifest,settings=read_package(first)
        self.assertEqual(manifest['engine_contract'],OVERLAY_CONTRACT)
        self.assertNotEqual(files['CPALACE.DAT'],files['patched/CPALACE.DAT'])
        import_package(first,Path(self.tmp.name)/'imported').export_zip(second)
        self.assertEqual(first.read_bytes(),second.read_bytes())
        e.enabled_phases=(0,2)
        with self.assertRaises(CompositeProjectError):p.validate_phase_policy(e)

    def test_roles_distinguish_transparency_and_opaque_replacement(self):
        palace={rid:role for rid,label,role in wall_components(FAMILIES[1],OVERLAY_CONTRACT)}
        self.assertEqual(palace[1619],'Base artwork');self.assertEqual(palace[1603],'Transparent overlay')
        dungeon={rid:role for rid,label,role in wall_components(FAMILIES[0])}
        self.assertEqual(dungeon[1613],'Opaque replacement')

    def test_layer_mask_and_before_after_use_native_draw_order(self):
        commands=[['i',FAMILIES[1],1619,40,40,0],['i',FAMILIES[1],1603,40,40,16]]
        base=render_recipe(commands[:1],self.ws.archives)
        final=render_recipe(commands,self.ws.archives)
        self.assertEqual(final.bits[40*640+80:40*640+82],base.bits[40*640+80:40*640+82])
        self.assertEqual(final.pick(80,40),(FAMILIES[1],1619))
        self.assertEqual(final.pick(82,40),(FAMILIES[1],1603))
        self.assertEqual(without_overlays(commands,FAMILIES[1]),commands[:1])
        raster,crop,cmd=overlay_inspector(commands,FAMILIES[1],1603,self.ws.archives,self.ws.projects,self.ws.settings)
        self.assertEqual(len(raster.pixels),640*200*3)
        self.assertIn(bytes((50,220,235)),raster.pixels)
        a=self.ws.archives[FAMILIES[1]];im=a.analysis_by_id(1603)
        e=self.ws.projects[FAMILIES[1]].edit_for_image(a,im.resource.index,im.image);e.bits[4]^=1
        changed,_,_=overlay_inspector(commands,FAMILIES[1],1603,self.ws.archives,self.ws.projects,self.ws.settings)
        self.assertNotEqual(raster.pixels,changed.pixels)
        with self.assertRaises(ValueError):overlay_inspector(commands,FAMILIES[1],1604,self.ws.archives)

if __name__=='__main__':unittest.main()
